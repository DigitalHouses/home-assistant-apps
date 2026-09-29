# DigitalHouses Telemetry Privacy / Legal Review

Status: architecture/legal-risk review for public telemetry rollout  
Review date: 2026-09-29  
Scope: DigitalHouses product telemetry sent to `https://telemetry.digitalhouses.vip`

This document is an engineering compliance review, not a substitute for advice from qualified counsel in each applicable jurisdiction.

## 1. Executive conclusion

The current telemetry data model is intentionally minimal, but it is not safe to assume that mandatory telemetry with no consent/objection path is lawful merely because the product is optional to install.

The main reasons are:

1. a persistent random installation identifier is a pseudonymous identifier rather than guaranteed anonymous data;
2. the request source IP is necessarily processed in transit by the network/edge even when DigitalHouses does not retain it;
3. Kazakhstan law generally requires consent for collection/processing of personal data unless a statutory exception applies;
4. the reviewed Kazakhstan exceptions do not clearly cover ordinary private product-adoption telemetry;
5. GDPR can permit processing without consent under another lawful basis such as legitimate interests, but that requires a documented necessity/balancing analysis and normally preserves the data subject's right to object;
6. EU ePrivacy rules can independently regulate storage/access to information on terminal equipment, including identifiers, even when the GDPR lawful basis is not consent.

Therefore telemetry policy v2 may remain the desired technical architecture, but **mandatory public rollout is legally gated** until the applicable lawful basis, user-rights model, controller identity, and infrastructure jurisdiction are documented.

## 2. Current telemetry data

Protocol v1 sends:

```text
schema
telemetry_policy_version
installation_id (random UUIDv4)
product
version
```

Country is derived server-side from network metadata.

The DigitalHouses application database does not intentionally retain source IP.

No customer/site name, Home Assistant UUID, hostname, LAN/WAN address, device inventory, entity IDs, configuration values, monitored values, or credentials belong in the telemetry payload.

This data-minimization design should be preserved regardless of the final legal basis.

## 3. Kazakhstan

Primary source:

- Law of the Republic of Kazakhstan "On Personal Data and their Protection":  
  https://adilet.zan.kz/rus/docs/Z1300000094

### 3.1 Consent is the default rule

Article 7 states that collection and processing of personal data are performed with the consent of the data subject or representative, except for statutory exceptions.

Article 8 requires consent to be given in a form that allows confirmation that consent was received and provides for withdrawal.

Engineering consequence:

> "The software is optional; users who dislike telemetry should not use it" is not, by itself, a documented statutory exception to the consent rule.

### 3.2 Exceptions do not clearly cover ordinary product telemetry

Article 9 lists cases where collection/processing may occur without consent. The reviewed list includes state functions, state statistics, journalism/creative activity, specific financial/tax/public-law cases and other cases established by law.

Ordinary private product-adoption/version telemetry is not clearly identified as one of those exceptions.

Until qualified Kazakhstan counsel identifies a specific applicable exception, the architecture must not assume that Article 9 authorizes mandatory telemetry without consent.

### 3.3 Purpose limitation and data minimization

Article 7 requires collection/processing to be limited to specific, predetermined and lawful purposes and prohibits excessive data.

DigitalHouses should keep one explicit telemetry purpose:

```text
product adoption, active-installation measurement,
version distribution and operational release support
```

Do not silently expand telemetry to diagnostics, device inventories, configuration, usage behavior or customer/site data.

### 3.4 Data localization

Article 12 requires storage of personal data in a database and/or digital object located in Kazakhstan.

Before public rollout, verify and document:

- physical/jurisdictional location of the primary telemetry PostgreSQL database;
- database backups and replicas;
- log destinations;
- monitoring/analytics copies;
- whether any retained personal/pseudonymous data leaves Kazakhstan.

If the telemetry database is the current CT7000 deployment in Kazakhstan, that is directionally consistent with the localization requirement, but backups and processors still require review.

### 3.5 Cross-border processing / Cloudflare

Article 16 regulates cross-border transfer.

The current request path uses Cloudflare before the DigitalHouses service. Even when the application stores only a country code, Cloudflare necessarily handles source network information to deliver the request.

Required action:

- document Cloudflare's role as processor/service provider;
- document where request metadata may be processed;
- determine whether the configured Cloudflare path creates a Kazakhstan cross-border-transfer issue;
- ensure logs/analytics do not retain IP contrary to the public disclosure.

### 3.6 Registration / notification

Kazakhstan added Article 10-1 on notification of the authorized body about commencement/termination of personal-data processing. Small and medium owners/operators are exempt from that notification requirement; classification must be checked against the current implementing rules.

Required action:

- determine DigitalHouses operator classification before assuming notification is unnecessary.

## 4. European Union / EEA

Primary sources:

- GDPR: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- EDPB legal-basis materials: https://www.edpb.europa.eu/topics/key-gdpr-concepts/legal-basis_en
- EDPB Guidelines 1/2024 on legitimate interests: https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-12024-processing-personal-data-based-article-61f_en
- EDPB pseudonymisation guidance: https://www.edpb.europa.eu/news/edpb-adopts-pseudonymisation-guidelines-and-paves-way-improve-cooperation-competition_en
- EDPB Guidelines 2/2023 on Article 5(3) ePrivacy scope: https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-22023-technical-scope-art-53-eprivacy-directive_en

### 4.1 Persistent UUID is not automatically anonymous

EDPB guidance treats pseudonymised data that can still be related to an identifiable person as personal data.

A stable installation UUID associated with repeated network requests should therefore be treated conservatively as pseudonymous personal data for GDPR architecture.

### 4.2 Consent is not the only possible GDPR legal basis

GDPR Article 6 provides several lawful bases. For this telemetry, the plausible non-consent candidate is legitimate interests.

Using legitimate interests requires a documented three-part analysis:

1. a lawful, specific and present legitimate interest;
2. necessity of the processing for that interest;
3. balancing against the individual's rights and freedoms.

The fact that telemetry is useful to DigitalHouses is not enough by itself.

### 4.3 Right to object

Where processing relies on legitimate interests, GDPR Article 21 gives the data subject a right to object. The controller must stop unless it demonstrates compelling legitimate grounds that override the individual's interests/rights or the processing is needed for legal claims.

Engineering consequence:

> a permanent "no opt-out under any circumstances" rule is high-risk if legitimate interests is the chosen GDPR basis.

### 4.4 ePrivacy is a separate issue

EDPB's final Guidelines 2/2023 interpret Article 5(3) ePrivacy broadly for storage/access to information in terminal equipment.

The DigitalHouses client creates and reads a persistent installation identifier on the user's system. Because core product functionality is explicitly designed to remain operational without the telemetry service, treating this telemetry identifier as "strictly necessary" to the requested core service would require a strong jurisdiction-specific analysis.

A GDPR legitimate-interest assessment alone does not resolve the ePrivacy question.

### 4.5 Transparency

If GDPR applies, the public notice should include at least:

- controller identity and contact;
- purposes;
- categories/data fields;
- lawful basis;
- legitimate interests if relied upon;
- recipients/processors;
- international transfers;
- retention;
- data-subject rights;
- complaint/supervisory-authority information;
- whether provision of data is required and consequences of not providing it.

## 5. California

Primary sources:

- California Attorney General CCPA overview:  
  https://oag.ca.gov/privacy/ccpa
- California Privacy Protection Agency:  
  https://cppa.ca.gov/

CCPA/CPRA applies only if the operator meets the statutory applicability tests.

A unique identifier and IP address can fall within the definition of personal information. If DigitalHouses becomes subject to CCPA/CPRA, notice-at-collection and applicable access/deletion/correction rights must be implemented. Sale/share opt-out is a separate issue and is not triggered merely by first-party telemetry where no sale/share occurs.

Action:

- periodically reassess CCPA applicability as DigitalHouses grows rather than claiming either applicability or exemption permanently.

## 6. Blocking issues before mandatory public telemetry

Do not mark mandatory public telemetry legally cleared until all of these are resolved:

- [ ] identify the legal controller/operator by real legal name;
- [ ] record required registration/business identifier where applicable;
- [ ] publish a real privacy contact channel;
- [ ] confirm telemetry database physical/jurisdictional location;
- [ ] document backup/replica/log locations;
- [ ] document Cloudflare/other processors and cross-border path;
- [ ] choose and document the Kazakhstan lawful basis;
- [ ] choose and document the EU GDPR lawful basis if EU scope applies;
- [ ] resolve EU ePrivacy consent/necessity analysis if EU distribution is in scope;
- [ ] define consent withdrawal / objection behavior where required;
- [ ] define retention duration instead of indefinite retention unless a defensible necessity exists;
- [ ] document data-subject access/deletion workflow;
- [ ] confirm whether Kazakhstan Article 10-1 notification applies to the operator;
- [ ] publish final privacy notice before collection begins under the new policy.

## 7. Architecture recommendation

### Safest public model

For a globally distributed Home Assistant product, the lowest-risk current architecture is:

```text
explicit telemetry opt-in
+ minimal protocol payload
+ no source-IP retention
+ clear privacy notice
+ authenticated deletion
+ withdrawal disables future telemetry
```

This model is also already implemented by the existing policy-v1 clients.

### If DigitalHouses keeps mandatory telemetry

Do not rely on "do not use the product" as the legal basis.

Before rollout, obtain jurisdiction-appropriate legal confirmation for:

- Kazakhstan consent/exemption;
- EU GDPR legal basis and Article 21 handling;
- EU ePrivacy requirements;
- cross-border processing;
- final controller/operator disclosure.

Until then, policy v2 should be treated as a **technical target under legal hold**, not as authorization to remove opt-in from public releases.

## 8. Data-retention recommendation

The current indefinite heartbeat-history policy is difficult to justify under storage-limitation principles.

Recommended split:

- installation record: retain while the installation remains observed/active plus a defined inactivity window;
- raw heartbeat history: retain for a defined operational/statistical period;
- long-term trend reporting: retain aggregated/de-identified statistics instead of raw installation-level history.

The exact periods should be chosen after confirming actual reporting needs.

## 9. Required public wording inputs

A final privacy notice cannot be completed honestly until these facts are supplied:

```text
Controller/operator legal name:
Country / legal address:
BIN/IIN or other registration identifier, if applicable:
Privacy contact:
Telemetry database location:
Cloudflare account/processor role:
Other processors/subprocessors:
Retention periods:
Supported distribution jurisdictions:
Chosen lawful basis by jurisdiction:
```

Do not publish placeholders for those fields.
