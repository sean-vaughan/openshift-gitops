# profiles/data-centers/

Data-center-specific configuration overrides.

A data-center profile holds infrastructure-specific defaults that vary by physical
or cloud location: storage class names, network CIDRs, registry mirrors, proxy
settings, etc. These are not repeated across every app; they are declared once per
data-center and applied as a profile layer (see ADR-0003 cascade).

## Naming

Data-center short codes match the `<dc>` segment of cluster names (ADR-0007).

```
data-centers/
  rdu/      Raleigh data center
  chi/      Chicago data center
  use1/     AWS us-east-1
```

## Adding a data-center

1. Create `profiles/data-centers/<dc>/` with infrastructure-specific values.
2. Add the `dc` code to the taxonomy in ADR-0007.
3. Wire to relevant clusters via gate files or a data-center-scoped ApplicationSet.
