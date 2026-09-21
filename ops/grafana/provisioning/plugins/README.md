Empty on purpose: the dashboards need no app plugin. The directory exists because
Grafana logs an error on every start for a provisioning directory it expects and cannot
find.

The Prometheus **datasource** is a plugin too, since Grafana 12, and is not configured
here: Grafana installs it from grafana.com on first start. A Grafana that cannot reach
the internet needs it installed beforehand - `grafana cli plugins install prometheus`,
or baked into the image - or every panel reports its datasource missing.
