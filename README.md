# GS1 Germany Web Vocabulary

This repository was set up to for the maintenance and further development of the GS1 Germany Web Vocabulary.

## What is the GS1 (Germany) Web Vocabulary?

The GS1 Web Vocabulary (WebVoc), an official extension to schema.org, is a method for describing trade items, companies, locations, and more using linked data concepts. This structured data, often in the form of JSON-LD documents, enables IT applications to understand the contained information semantically. All globally defined terms are accessible both in a human-friendly way as well as in machine-readable datasets (see <https://ref.gs1.org/voc/>). To address country-specific demands and to facilitate easier migration, GS1 Germany provides an own Web Vocabulary in a similar manner.

Therefore, GS1 Germany's WebVocab is a subset of the global one.

## Business benefits

*What's in it for my company?* The GS1 (Germany) Web Vocabulary enables various use cases:

1. When embedded in the source code of your Web Pages, it helps search engines and other accessing applications to better find your trade items when consumers look for specific products.
2. It also allows your company to provide structured data (e.g.  location, company, product master data files and more) that your trading partners can easily understand/integrate. There are several ways to link to these files (e.g. indexing in *Verified by GS1*, pointing directly to it via a GS1 Digital Link URI, etc).
3. In addition, it can also be embedded in EPCIS events, contributing to better scalability and interoperability.

## Versioning

We apply semantic versioning, i.e. MAJOR.MINOR.PATCH.
Applied to this WebVoc, this means:

- MAJOR: not backward compatible changes
- MINOR: backward compatible modifications such as adding new or removing properties, classes, and code values
- PATCH: small changes such as fixing typos

## How to contribute

The addition of new classes, properties, and code lists/values needs to comply with GS1 Germany's standardisation process (see [GS1 Germany Gremienhandbuch](https://www.gs1-germany.de/fileadmin/gs1/basis_informationen/gs1-germany-handbuch-gremienstruktur.pdf) for further information).

At the same time, in case you encounter an issue or have a suggestion for improvement, feel free to either [submit an Issue](https://github.com/gs1-germany/gs1GermanyWebVoc/issues) or [make a Pull Request](https://github.com/gs1-germany/gs1GermanyWebVoc/pulls). Any help or support is highly appriciated.
