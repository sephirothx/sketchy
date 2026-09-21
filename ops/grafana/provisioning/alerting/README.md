Empty on purpose. Alerting lives in Prometheus's rules
([`ops/prometheus/rules/`](../../../prometheus/rules/), R-OBS-13), where CI checks every
series each rule names; Grafana only draws. The directory exists because Grafana logs an
error on every start for a provisioning directory it expects and cannot find.
