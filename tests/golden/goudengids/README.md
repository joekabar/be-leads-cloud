# Golden HTML fixtures — goudengids

Hand-constructed minimal HTML exercising all selectors defined in
`.claude/skills/goudengids-listing/references/selectors.md`.

| File | Description |
|---|---|
| `listing_antwerpen_electriciens_page1.html` | 12 cards; full field coverage including Bellock reference card, multi-phone card, no-website card, invalid-phone card |
| `listing_brugge_bakkers_page2.html` | 6 cards; sparse fields (bakeries, few with website) |
| `listing_no_results.html` | Empty-state page with `.empty-state` + "geen resultaten" text; 0 cards |
| `listing_french_liege_plombiers.html` | FR variant (pagesdor structure); 4 cards with French addresses |

## Bellock reference card

The Bellock card in `listing_antwerpen_electriciens_page1.html` is the canonical test case:

```
name: "Bellock"
href: "/bedrijf/Antwerpen/L389732/Bellock/"
phone (primary): "+3232361306"
website: "https://www.bellock.be" (stripped of utm_ query)
street: "Lange Van Bloerstraat 116"
postal_code: "2060"
city: "Antwerpen"
description: "Electrotechnical installer since 1989"
```
