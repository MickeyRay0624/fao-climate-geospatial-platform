# Data profiles

Data profiles are versioned validation contracts attached to an exact dataset version. A profile does not change the source asset. It records structured quality evidence and creates an authorised representation for preview and downstream selection.

## Native administrative boundary

`administrative-boundary@1.0` accepts a non-empty GeoJSON `FeatureCollection` containing `Polygon` or `MultiPolygon` geometry. Every feature must have a non-empty, unique `area_code`, plus `area_name` and `admin_level`. `parent_code` and `parent_name` are optional.

The validator records the feature count, property schema, geometry types, extent and coordinate policy. Missing or invalid geometry, duplicate identifiers, missing required fields and non-polygon geometry are blocking. When a GeoJSON document has no explicit CRS member, the validator records an RFC 7946/WGS84 assumption warning; it does not claim that the original source file declared a CRS.

## Native normalised indicator layer

`normalised-indicator-layer@1.0` accepts CSV or GeoJSON properties with:

- `area_code`
- `value`
- `indicator_code`
- `unit`
- `direction`
- `time_start`
- `time_end`

One layer represents one indicator and one unit. Area codes must be unique. The current illustrative investment method accepts `higher_is_priority` and pre-normalised numeric values from zero through one. Missing values are warnings and remain visible to the method's approved missing-value policy; duplicate area codes, mixed indicator codes, inconsistent units, unsupported direction and invalid ranges are blocking.

Only published versions can be frozen into a formal investment input set. A successful file validation alone does not grant publication or analysis authority.

## Generic and compatibility profiles

`generic-vector@1.0` and `generic-table@1.0` support governed catalogue evidence that does not yet meet an application-specific contract. They remain valid historical records but cannot substitute for the native profiles in a formal separate-layer input set.

`analysis-ready-priority-bundle@1.0` is retained for the preserved synthetic demonstrator. It is a compatibility profile and is not a contract for real operational data.

All profile versions preserve source checksums, scan status, quality issues, representations and lineage. Published versions and their assets remain immutable; corrected data is released as a new version that explicitly supersedes or derives from the earlier evidence.
