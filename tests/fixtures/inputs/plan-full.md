# Delivery plan: Visitor registration at the main office

## Background

Visitors sign a paper book at the reception today. The book is hard to read, and nobody knows who is in the
building during a fire drill.

## Goals and success measures

- Every visitor is registered before entering; success means no paper book after the first month.
- Reception staff need under one minute per visitor, measured in the first two weeks.

## Users and roles

- Receptionists register visitors and print badges.
- Hosts are notified when their visitor arrives.
- The security officer sees who is in the building.

## Scope

In scope: registration at the reception desk, host notification, the list of people in the building.
Out of scope: parking, recurring visitor passes, the other offices.

## Integrations

The host is notified through the existing email service, and employee names come from the HR system's nightly
export.

## Security

Receptionists sign in with the organisation's single sign-on; the security officer's list is visible to the
security role only.

## Privacy

Visitors are told at registration that their visit record is deleted 30 days after the visit, under the GDPR.

## Accessibility

The registration screen meets WCAG 2.2 AA and is available in Finnish and English.

## Performance

The list of people in the building updates within five seconds of a registration.

## Deployment

It runs on the organisation's Azure tenant, with a staging and a production environment.

## Constraints

The budget is 40 000 euros, and the first version must be in use by the end of March.

## Decisions

1. Badges are printed on the existing label printer at the reception.
2. Hosts are notified by email only; no text messages in the first version.
3. The register keeps no photo of the visitor.
