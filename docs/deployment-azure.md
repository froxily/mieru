# Deploying MIERU to Azure Container Apps

MIERU runs as one container: FastAPI serves the API and the built React app, and a read-only DuckDB file holds the Olist demo data. Uploaded files live on the container's own disk and are deleted after 60 minutes, or sooner when the app scales to zero. Nothing is stored outside the container.

## Target configuration

| Setting | Value | Why |
|---|---|---|
| Plan | Container Apps, Consumption | Billed per second only while a replica runs |
| Region | Central India | Allowed by the subscription's region policy; one Container Apps environment per region is permitted, and Malaysia West's slot is already used |
| Resource group | `mieru-rg` | Separate cost tracking and clean removal |
| Environment | `mieru-env`, Consumption only, logs destination `none` | No Log Analytics charges, isolated from other apps |
| Image | `ghcr.io/froxily/mieru:<git sha>` (public GHCR package) | No paid Azure Container Registry |
| CPU / memory | 0.5 vCPU / 1 GiB | Smallest size that passed the load test (see below) |
| Replicas | min 0, max 1, HTTP scaler at 10 concurrent requests | Scale to zero when idle; spending is capped at one replica |
| Ingress | External, HTTPS only, target port 8000 | Default `*.azurecontainerapps.io` hostname and certificate |
| Secret | `session-secret` → `MIERU_SESSION_SECRET` | 64 random hex characters, stored as a Container Apps secret |
| Probes | Startup and readiness on `GET /api/health` | Traffic only reaches a ready replica |

Production defaults are baked into the image (`MIERU_ENV=production`, 20 MB / 250,000-row uploads, one processing worker, DuckDB limited to 512 MB and one thread). Every value can be overridden with an environment variable; see `.env.example`.

## Costs

Container Apps prices in Central India (Azure Retail Prices API, November 2026): active vCPU USD 0.000024 per second, memory USD 0.000003 per GiB-second. On this subscription no monthly free grant appears in the usage records or the credit ledger, so the estimate assumes billing from the first second.

At 0.5 vCPU / 1 GiB a running replica costs about USD 0.054 per hour. A replica stays up for the 300-second cooldown after the last request, so even a short visit costs about USD 0.005–0.01.

| Scenario | Active hours / month | Estimated cost / month |
|---|---|---|
| Light (about 20 visits) | 3–4 | USD 0.15–0.22 |
| Moderate (about 100 visits) | 15–20 | USD 0.80–1.10 |
| Kept awake all month by traffic | 720 | USD 39 (the hard ceiling with one replica) |

The ceiling is why a subscription budget with e-mail alerts is part of the deployment.

## Deploy

Prerequisites: the image has been pushed by CI and its GHCR package is public; `az` is logged in to the student subscription.

```bash
az group create --name mieru-rg --location malaysiawest
```
```bash
az containerapp env create --name mieru-env --resource-group mieru-rg --location centralindia --logs-destination none
```
```bash
az containerapp create --name mieru --resource-group mieru-rg --environment mieru-env --image ghcr.io/froxily/mieru:<sha> --target-port 8000 --ingress external --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 --scale-rule-name http-scaler --scale-rule-type http --scale-rule-http-concurrency 10 --secrets session-secret=<64-hex-chars> --env-vars MIERU_SESSION_SECRET=secretref:session-secret
```

The live app was created from an equivalent YAML spec that also sets startup, readiness and liveness probes on `/api/health` and `allowInsecure: false` (plain HTTP is redirected to HTTPS). The session secret was generated locally and passed only in that spec, which was deleted after use.

## Update and roll back

Each release is an image tagged with its Git commit. To deploy or roll back, point the app at another tag; Container Apps creates a new revision and moves traffic to it:

```bash
az containerapp update --name mieru --resource-group mieru-rg --image ghcr.io/froxily/mieru:<sha>
```

List revisions with `az containerapp revision list --name mieru --resource-group mieru-rg -o table`.

## Remove

Deleting the resource group removes the app and its environment and stops all charges. It does not touch the other projects.

## Cost controls

- A monthly subscription-wide budget of ₹220 with e-mail alerts at 50%, 80% and 100% of actual spend and at 80% and 100% of forecast spend. It is an alert threshold, not a spending cap.
- `max-replicas 1` caps spending at one replica.
- Logs go nowhere: no Log Analytics workspace exists. `az containerapp logs show` still streams live console output when needed.

## Data licence

The image contains a database and figures derived from the Olist dataset, which is licensed CC BY-NC-SA 4.0. MIERU is a non-commercial demo, credits Olist in the app and in `NOTICE`, and distributes the derived files under the same licence.

## Live deployment

- URL: https://mieru.braveocean-6888a480.centralindia.azurecontainerapps.io
- Resource group `mieru-rg`, environment `mieru-env` (Central India), app `mieru`.
