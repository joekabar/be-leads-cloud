# KBO Enterprise Number Checksum

## Algorithm

Belgian enterprise numbers use a mod-97 check digit (same family as IBAN):

```
int(first_8_digits) % 97 == 97 - int(last_2_digits)
```

For `0439401387`:
- First 8 digits: `04394013`
- Last 2 digits: `87`
- Check: `4394013 % 97 = 10` → `97 - 10 = 87` ✓

## Prefix rules

- **Legacy allocation**: numbers start with `0` (e.g. `0439401387`)
- **Modern allocation**: numbers may start with `1` (expanded range, still valid)
- Format in official documents: `0439.401.387` (dots after position 4 and 7)
- The `BE` prefix is added for EU VAT purposes: `BE0439401387`

## Implementation

**Never roll your own implementation.** Always use `stdnum.be.vat`:

```python
from stdnum.be import vat

vat.is_valid("0439401387")    # True
vat.is_valid("0439401388")    # False (wrong check digit)
vat.compact("0439.401.387")   # "0439401387"
vat.validate("BE0439401387")  # "0439401387"
```

`stdnum.be.vat.validate()` raises `stdnum.exceptions.ValidationError` on invalid input.
`vat.compact()` strips dots, spaces, and the `BE` prefix without validating the checksum.
