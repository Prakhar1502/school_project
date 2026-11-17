# Running the register online with Cloudflare (free)

The online version works on any phone or computer with internet. No laptop needs to stay on.
It runs on Cloudflare Workers, and the data is stored in Cloudflare's D1 database. One school fits easily in Cloudflare's free plan.

## How it fits together

- `index.html` is the app. It's the same file as the laptop version.
- `worker/index.js` is the small online backend. It answers `/api/...` and saves to D1.
- `wrangler.jsonc` holds Cloudflare's settings. It points to the backend, the files and the database.
- The **PIN** is a Cloudflare *secret*, so it's never stored in GitHub.

## Setup

These steps assume the Worker is already connected to this GitHub repo through **Workers & Pages → Create → Import a repository**.

### 1. Build settings

Go to **Worker → Settings → Build** and edit the build configuration.

| Setting | Value |
|---|---|
| Build command | *(leave empty)* |
| Deploy command | `npx wrangler deploy` |
| Root directory | `/` |

### 2. Set the PIN

Go to **Worker → Settings → Variables and Secrets → Add**.

- Type: **Secret**
- Variable name: `REGISTER_PIN`
- Value: the PIN you want (for example 6 digits). Don't use something easy to guess, like `1234` or a birth year.

Click **Deploy** to save.

### 3. Deploy

Every push to `main` deploys automatically. You can also open **Deployments** and click **Retry build**.

On the first deploy, Cloudflare creates the D1 database (`school-fee-register`) by itself. The log shows lines like `Provisioning DB (D1 Database)…`.

### 4. Open it

Open `https://school-project.<your-subdomain>.workers.dev`, enter the PIN, and start in **Settings**. Set the school name, the session start and the class fees.

On each phone: open the same address, enter the PIN once, then use **⋮ → Add to Home screen**.

## Changing the PIN

Edit the `REGISTER_PIN` secret. Devices that are already signed in stay signed in. To sign everyone out, run this in **Workers & Pages → D1 → school-fee-register → Console**:

```sql
DELETE FROM tokens;
```

## Backups

- **Payments → Export CSV** downloads everything as a spreadsheet. Do it every month.
- D1's **Time Travel** can restore the database to an earlier point. See **D1 → school-fee-register → Time Travel** in the dashboard.

## Notes

- Data is stored in your Cloudflare account. Only people who know the PIN can see or change it.
- Wrong PINs are limited to 8 tries per 10 minutes from each internet address.
- The laptop version (`server.py`) still works on its own, but it keeps its own separate data. Pick one version for the school's real records.

## Running it locally (for developers)

```bash
npm i -g wrangler
echo "REGISTER_PIN=2468" > .dev.vars
wrangler dev
```

`.dev.vars` and the local `.wrangler/` database are git-ignored.
