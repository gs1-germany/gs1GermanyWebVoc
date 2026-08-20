#!/usr/bin/env python3
"""
GS1 Germany WebVoc - Ontology Quality Gate
============================================
Validates a JSON-LD ontology file (e.g. stagingVersion/gs1DEWebVoc.jsonld)
against the structural and content conventions established for the
GS1 Germany Web Vocabulary.

Usage:
    python validate_ontology.py <path-to-jsonld> [--baseline <path-to-previous-version>]

Exit codes:
    0 - no ERRORs (WARNINGs may still be present)
    1 - at least one ERROR found (fails the GitHub Actions job / blocks the PR)

Design notes:
    - Findings are split into ERROR (blocking) and WARNING (non-blocking, informational).
    - Each check is implemented as an isolated function returning a list of Finding.
    - The "baseline" comparison (previous released version) is optional; if not
      provided, breaking-change detection (Check 7) is skipped with a WARNING.
"""

import json
import re
import sys
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # "ERROR" | "WARNING"
    check: str
    node_id: Optional[str]
    message: str

    def __str__(self):
        loc = f" [{self.node_id}]" if self.node_id else ""
        return f"{self.severity:7s} | {self.check:28s}{loc}: {self.message}"


ALLOWED_TERM_STATUS = {"testing", "stable", "deprecated"}
XSD_LITERAL_RANGES = {
    "xsd:string", "xsd:date", "xsd:dateTime", "xsd:float", "xsd:integer",
    "xsd:boolean", "xsd:gYear", "xsd:decimal", "rdf:langString",
}
PLACEHOLDER_PATTERNS = [
    r"\btbd\b", r"\btodo\b", r"\bplaceholder\b", r"\bxxx\b",
    r"\blorem ipsum\b", r"\bn/?a\b", r"\bdefinition needed\b",
    r"\bfixme\b", r"\bwip\b",
]
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def type_list(node: dict) -> list:
    t = node.get("@type")
    if t is None:
        return []
    return t if isinstance(t, list) else [t]


def get_id_ref(value: Any) -> Optional[str]:
    """Extract an @id string from a {'@id': ...} dict, list of such dicts (first), or None."""
    if isinstance(value, dict):
        return value.get("@id")
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("@id")
    return None


def get_id_refs(value: Any) -> list:
    """Extract all @id strings from a {'@id':...} dict or list of such dicts."""
    if isinstance(value, dict):
        return [value.get("@id")] if value.get("@id") else []
    if isinstance(value, list):
        return [v.get("@id") for v in value if isinstance(v, dict) and v.get("@id")]
    return []


# ---------------------------------------------------------------------------
# Check 1: No duplication of terms (@id uniqueness)
# ---------------------------------------------------------------------------

def check_no_duplicates(graph: list) -> list:
    findings = []
    ids = [n.get("@id") for n in graph if n.get("@id")]
    counts = Counter(ids)
    for node_id, count in counts.items():
        if count > 1:
            findings.append(Finding(
                "ERROR", "no-duplicate-terms", node_id,
                f"@id appears {count} times in @graph (must be unique)."
            ))
    return findings


# ---------------------------------------------------------------------------
# Check 2: Valid JSON-LD (structural + optional real expansion via pyld)
# ---------------------------------------------------------------------------

def check_jsonld_expansion(data: dict) -> list:
    findings = []
    try:
        from pyld import jsonld  # optional dependency, install in CI via requirements.txt
        try:
            jsonld.expand(data)
        except Exception as e:
            findings.append(Finding(
                "ERROR", "valid-jsonld-expansion", None,
                f"JSON-LD expansion failed: {e}"
            ))
    except ImportError:
        findings.append(Finding(
            "WARNING", "valid-jsonld-expansion", None,
            "pyld not installed - skipped real JSON-LD expansion test. "
            "Install 'pyld' in the CI environment for a stronger guarantee."
        ))
    return findings


def check_undeclared_prefixes(data: dict) -> list:
    findings = []
    ctx = data.get("@context", {})
    declared = set(ctx.keys())
    used = set()

    def scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "@id" and isinstance(v, str) and ":" in v and not v.startswith("http"):
                    used.add(v.split(":")[0])
                if isinstance(k, str) and ":" in k and not k.startswith("@"):
                    used.add(k.split(":")[0])
                scan(v)
        elif isinstance(obj, list):
            for item in obj:
                scan(item)

    for node in data.get("@graph", []):
        scan(node)

    undeclared = used - declared
    for prefix in sorted(undeclared):
        findings.append(Finding(
            "ERROR", "undeclared-prefix", None,
            f"Prefix '{prefix}:' is used but not declared in @context."
        ))

    unused = declared - used - {"owl", "rdf", "rdfs", "xsd"}  # core prefixes used structurally
    for prefix in sorted(unused):
        findings.append(Finding(
            "WARNING", "unused-prefix", None,
            f"Prefix '{prefix}:' is declared in @context but never used in @graph."
        ))
    return findings


# ---------------------------------------------------------------------------
# Check 3: Impermissible characters
# ---------------------------------------------------------------------------

def check_impermissible_characters(graph: list) -> list:
    findings = []

    def scan_string(node_id, field_name, s):
        local = []
        if CONTROL_CHAR_RE.search(s):
            local.append(Finding(
                "ERROR", "impermissible-characters", node_id,
                f"Field '{field_name}' contains control characters."
            ))
        if s != s.strip() and field_name in ("@type",):
            local.append(Finding(
                "ERROR", "impermissible-characters", node_id,
                f"Field '{field_name}' has leading/trailing whitespace: {s!r}"
            ))
        # unbalanced simple HTML tags (opening <p> without closing, or vice versa)
        opens = len(re.findall(r"<p>", s, flags=re.IGNORECASE))
        closes = len(re.findall(r"</p>", s, flags=re.IGNORECASE))
        if opens != closes:
            local.append(Finding(
                "WARNING", "impermissible-characters", node_id,
                f"Field '{field_name}' has unbalanced <p>/</p> tags ({opens} open, {closes} close)."
            ))
        # keys/ids must not contain spaces or trailing colons
        return local

    def scan(node_id, obj, field_name=""):
        local = []
        if isinstance(obj, str):
            local.extend(scan_string(node_id, field_name, obj))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k.endswith(":") or k.endswith("::"):
                    local.append(Finding(
                        "ERROR", "impermissible-characters", node_id,
                        f"Property key '{k}' has a malformed trailing colon."
                    ))
                local.extend(scan(node_id, v, k))
        elif isinstance(obj, list):
            for item in obj:
                local.extend(scan(node_id, item, field_name))
        return local

    for node in graph:
        nid = node.get("@id")
        findings.extend(scan(nid, node))
    return findings


# ---------------------------------------------------------------------------
# Check 4: Plausibility - property/class association (domain & range)
# ---------------------------------------------------------------------------

def check_property_class_plausibility(graph: list) -> list:
    findings = []
    by_id = {n.get("@id"): n for n in graph if n.get("@id")}

    def is_known_external(ref_id: str) -> bool:
        # allow references into other, externally maintained vocabularies
        return any(ref_id.startswith(p) for p in ("gs1:", "schema:", "xsd:", "rdf:", "owl:"))

    for node in graph:
        nid = node.get("@id")
        types = type_list(node)
        is_obj_prop = "owl:ObjectProperty" in types
        is_data_prop = "owl:DatatypeProperty" in types
        if not (is_obj_prop or is_data_prop):
            continue

        for field_name in ("rdfs:domain", "rdfs:range"):
            refs = get_id_refs(node.get(field_name))
            for ref in refs:
                if ref.startswith("gs1de:") and ref not in by_id:
                    findings.append(Finding(
                        "ERROR", "plausibility-property-class", nid,
                        f"{field_name} points to '{ref}', which is not defined in this file."
                    ))
                elif not ref.startswith("gs1de:") and not is_known_external(ref):
                    findings.append(Finding(
                        "WARNING", "plausibility-property-class", nid,
                        f"{field_name} points to '{ref}' from an unrecognised namespace."
                    ))

        range_ref = get_id_ref(node.get("rdfs:range"))
        if range_ref:
            if is_obj_prop and range_ref in XSD_LITERAL_RANGES:
                findings.append(Finding(
                    "ERROR", "plausibility-property-class", nid,
                    f"owl:ObjectProperty has a literal range ({range_ref}); expected a class."
                ))
            if is_data_prop:
                target = by_id.get(range_ref)
                target_types = type_list(target) if target else []
                if "owl:Class" in target_types or "rdfs:Class" in target_types:
                    findings.append(Finding(
                        "ERROR", "plausibility-property-class", nid,
                        f"owl:DatatypeProperty has a class range ({range_ref}); expected a literal/datatype."
                    ))
    return findings


# ---------------------------------------------------------------------------
# Check 5: Structural conformity per object type
# ---------------------------------------------------------------------------

def classify_nodes(graph: list) -> dict:
    """Classify every node into one of: root, class, property, codelist_header, codelist_value."""
    by_id = {n.get("@id"): n for n in graph if n.get("@id")}
    header_ids = set()
    for n in graph:
        sc = get_id_ref(n.get("rdfs:subClassOf"))
        if sc == "gs1:TypeCode":
            header_ids.add(n["@id"])

    classification = {}
    for n in graph:
        nid = n.get("@id")
        types = type_list(n)
        if nid and nid.endswith(":") and nid == list(by_id.keys())[0] and \
                ("owl:Ontology" in types or "voaf:Vocabulary" in types):
            classification[nid] = "root"
        elif nid in header_ids:
            classification[nid] = "codelist_header"
        elif any(t in header_ids for t in types):
            classification[nid] = "codelist_value"
        elif "owl:Class" in types or "rdfs:Class" in types:
            classification[nid] = "class"
        elif "owl:ObjectProperty" in types or "owl:DatatypeProperty" in types:
            classification[nid] = "property"
        else:
            classification[nid] = "unknown"
    return classification


def check_structural_conformity(graph: list) -> list:
    findings = []
    classification = classify_nodes(graph)

    required_fields = {
        "class": ["rdfs:label", "rdfs:comment", "rdfs:subClassOf", "rdfs:isDefinedBy", "sw:term_status"],
        "property": ["rdfs:label", "rdfs:comment", "rdfs:domain", "rdfs:range", "rdfs:isDefinedBy", "sw:term_status"],
        "codelist_header": ["rdfs:label", "rdfs:subClassOf", "sw:term_status"],
        "codelist_value": ["rdfs:label", "rdfs:comment", "skos:prefLabel", "sw:term_status"],
    }
    forbidden_fields = {
        "codelist_header": ["rdfs:isDefinedBy", "@type"],
        "codelist_value": ["rdfs:isDefinedBy"],
    }

    for node in graph:
        nid = node.get("@id")
        kind = classification.get(nid)
        if kind in ("root", "unknown"):
            if kind == "unknown":
                findings.append(Finding(
                    "WARNING", "structural-conformity", nid,
                    "Could not classify node as class/property/codelist header/codelist value."
                ))
            continue

        for field_name in required_fields.get(kind, []):
            if field_name not in node:
                findings.append(Finding(
                    "ERROR", "structural-conformity", nid,
                    f"Missing required field '{field_name}' for a {kind.replace('_', ' ')}."
                ))

        for field_name in forbidden_fields.get(kind, []):
            if field_name in node:
                findings.append(Finding(
                    "ERROR", "structural-conformity", nid,
                    f"Field '{field_name}' should NOT be present on a {kind.replace('_', ' ')} "
                    f"(inconsistent with established convention)."
                ))

        # sw:term_status value check
        status = node.get("sw:term_status")
        if status and status not in ALLOWED_TERM_STATUS:
            findings.append(Finding(
                "ERROR", "structural-conformity", nid,
                f"sw:term_status='{status}' is not one of {sorted(ALLOWED_TERM_STATUS)}."
            ))

        # deprecated consistency
        has_deprecated_status = status == "deprecated"
        has_deprecated_link = "owl:deprecated" in node
        if has_deprecated_status != has_deprecated_link:
            findings.append(Finding(
                "ERROR", "structural-conformity", nid,
                "sw:term_status='deprecated' and owl:deprecated must both be present, or neither."
            ))

        # naming conventions
        local_name = nid.split(":")[-1] if nid else ""
        if kind == "class" and local_name and not local_name[0].isupper():
            findings.append(Finding(
                "WARNING", "naming-convention", nid,
                "Class names should be PascalCase (start with an uppercase letter)."
            ))
        if kind == "property" and local_name and local_name[0].isupper():
            findings.append(Finding(
                "WARNING", "naming-convention", nid,
                "Property names should be camelCase (start with a lowercase letter)."
            ))
        if kind == "codelist_value":
            pref_label = node.get("skos:prefLabel")
            suffix = nid.split("-", 1)[-1] if "-" in nid else None
            if suffix and pref_label and pref_label != suffix:
                findings.append(Finding(
                    "WARNING", "naming-convention", nid,
                    f"skos:prefLabel '{pref_label}' does not match the @id suffix '{suffix}'."
                ))
    return findings


# ---------------------------------------------------------------------------
# Check 6: rdfs:comment must be a proper definition
# ---------------------------------------------------------------------------

def check_comment_quality(graph: list, min_length: int = 15) -> list:
    findings = []
    for node in graph:
        nid = node.get("@id")
        comment = node.get("rdfs:comment")
        if comment is None:
            continue  # absence is already caught by structural-conformity check
        text = comment.get("@value") if isinstance(comment, dict) else comment
        if text is None:
            continue
        text_stripped = text.strip()
        if len(text_stripped) == 0:
            findings.append(Finding(
                "ERROR", "comment-quality", nid, "rdfs:comment is empty."
            ))
            continue
        if len(text_stripped) < min_length:
            findings.append(Finding(
                "ERROR", "comment-quality", nid,
                f"rdfs:comment is suspiciously short ({len(text_stripped)} chars): '{text_stripped}'"
            ))
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, text_stripped, flags=re.IGNORECASE):
                findings.append(Finding(
                    "ERROR", "comment-quality", nid,
                    f"rdfs:comment looks like a placeholder (matched /{pattern}/): '{text_stripped}'"
                ))
                break
        label = node.get("rdfs:label")
        label_text = None
        if isinstance(label, dict):
            label_text = label.get("@value")
        elif isinstance(label, list) and label:
            label_text = label[0].get("@value") if isinstance(label[0], dict) else None
        if label_text and text_stripped.lower() == label_text.strip().lower():
            findings.append(Finding(
                "WARNING", "comment-quality", nid,
                "rdfs:comment simply repeats rdfs:label instead of providing a real definition."
            ))
    return findings


# ---------------------------------------------------------------------------
# Check 7 (addition): Breaking-change detection vs. baseline
# ---------------------------------------------------------------------------

def check_breaking_changes(graph: list, baseline_graph: Optional[list]) -> list:
    findings = []
    if baseline_graph is None:
        findings.append(Finding(
            "WARNING", "breaking-change-detection", None,
            "No baseline file provided - skipped comparison against the previously released version."
        ))
        return findings

    current_by_id = {n.get("@id"): n for n in graph if n.get("@id")}
    baseline_by_id = {n.get("@id"): n for n in baseline_graph if n.get("@id")}

    removed = set(baseline_by_id) - set(current_by_id)
    for nid in sorted(removed):
        was_deprecated = baseline_by_id[nid].get("sw:term_status") == "deprecated"
        sev = "WARNING" if was_deprecated else "ERROR"
        findings.append(Finding(
            sev, "breaking-change-detection", nid,
            "Term existed in the baseline version but is missing from this file "
            + ("(was already deprecated)." if was_deprecated else
               "(removed without prior deprecation - breaking change for consumers).")
        ))

    for nid, current_node in current_by_id.items():
        baseline_node = baseline_by_id.get(nid)
        if not baseline_node:
            continue
        for field_name in ("rdfs:domain", "rdfs:range", "@type"):
            if current_node.get(field_name) != baseline_node.get(field_name):
                findings.append(Finding(
                    "WARNING", "breaking-change-detection", nid,
                    f"'{field_name}' changed compared to baseline "
                    f"(before: {baseline_node.get(field_name)!r}, now: {current_node.get(field_name)!r})."
                ))

    current_version = None
    baseline_version = None
    for n in graph:
        if "owl:versionInfo" in n:
            current_version = n["owl:versionInfo"]
    for n in baseline_graph:
        if "owl:versionInfo" in n:
            baseline_version = n["owl:versionInfo"]
    if current_version == baseline_version:
        findings.append(Finding(
            "ERROR", "breaking-change-detection", None,
            f"owl:versionInfo was not incremented (still '{current_version}')."
        ))
    return findings


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all_checks(data: dict, baseline_data: Optional[dict]) -> list:
    graph = data.get("@graph", [])
    baseline_graph = baseline_data.get("@graph") if baseline_data else None

    findings = []
    findings += check_no_duplicates(graph)
    findings += check_jsonld_expansion(data)
    findings += check_undeclared_prefixes(data)
    findings += check_impermissible_characters(graph)
    findings += check_property_class_plausibility(graph)
    findings += check_structural_conformity(graph)
    findings += check_comment_quality(graph)
    findings += check_breaking_changes(graph, baseline_graph)
    return findings


def main():
    parser = argparse.ArgumentParser(description="GS1 Germany WebVoc Quality Gate")
    parser.add_argument("file", help="Path to the JSON-LD ontology file to validate")
    parser.add_argument("--baseline", help="Path to the previous released version, for breaking-change detection")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    baseline_data = None
    if args.baseline:
        with open(args.baseline, encoding="utf-8") as f:
            baseline_data = json.load(f)

    findings = run_all_checks(data, baseline_data)

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    print(f"\n{'='*90}\nGS1 Germany WebVoc Quality Gate Report: {args.file}\n{'='*90}")
    print(f"Total nodes checked: {len(data.get('@graph', []))}")
    print(f"Findings: {len(errors)} ERROR(s), {len(warnings)} WARNING(s)\n")

    by_check = defaultdict(list)
    for f in findings:
        by_check[f.check].append(f)
    for check_name, items in by_check.items():
        print(f"--- {check_name} ({len(items)}) ---")
        for item in items:
            print(f"  {item}")
        print()

    if errors:
        print(f"❌ QUALITY GATE FAILED: {len(errors)} blocking error(s) found.")
        sys.exit(1)
    else:
        print(f"✅ QUALITY GATE PASSED ({len(warnings)} non-blocking warning(s)).")
        sys.exit(0)


if __name__ == "__main__":
    main()
