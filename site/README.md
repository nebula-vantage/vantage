# Vantage landing page

A standalone, responsive website for Vantage. Plain HTML, CSS, and JavaScript;
there is no package install or build step. Fonts are served locally, with their
SIL Open Font Licenses in `assets/fonts/`.

## Preview

From the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory site
```

Open <http://localhost:4173>. The page can also be hosted under a subdirectory;
asset paths are relative.

## Connect the signup form

Set `signupUrl` in [`config.js`](config.js) to the public HTTP or HTTPS URL of the
existing signup form. All four early access links use that destination, in the
same tab. This website does not collect or store signup details.

The page links to the [Vantage player survey](https://vantage-player-survey.anofdv3fe.chatgpt.site).
If the URL is removed or invalid, navigation and hero links lead to the early
access section, which says signup is unavailable; the final signup button stays
hidden.

## Publish

The Fly.io app is `vantage-landing`, serving the website at
<https://vantage-landing.fly.dev>. From the repository root, with `fly` installed
and authenticated to the account that owns the app:

```sh
fly deploy ./site --remote-only --ha=false
```

The remote builder uses [`Dockerfile`](Dockerfile) and [`Caddyfile`](Caddyfile) to
serve only the public website files on port 8080. No local Docker installation,
environment variables, database, or persistent volume is needed.
[`fly.toml`](fly.toml) enables HTTPS, checks the homepage, and uses one shared CPU
with 256 MB of memory in Toronto (`yyz`). The machine stops when idle and starts
on the next request; `--ha=false` avoids creating a spare machine.

To inspect the deployment:

```sh
fly status --config site/fly.toml
fly checks list --config site/fly.toml
```

The public files can also be deployed to another static website host with no
build step. Keep the server configuration and documentation out of its public
directory. Deployment is separate from the iPhone app and analysis pipeline.

## Page behavior

- The court replay is an illustration, labeled as such. It does not use match
  recordings or imply that the example is an actual analysis result.
- Play/pause, the timeline, and the player/ball overlay toggles are interactive.
  Replay starts only after a click and pauses when it leaves the viewport or
  the browser tab is hidden.
- FAQs use native HTML disclosures. Navigation, content, and disclosures work
  without JavaScript; signup configuration and replay controls require it.
- Reduced-motion preferences disable smooth scrolling and hover transitions.
- Copy describes current iPhone features; it does not promise unreleased match
  statistics, pricing, or an App Store launch date.

To verify a change, check desktop and mobile layouts, keyboard navigation, the
FAQ disclosures, replay controls, and that every early access link opens the
configured form. The website does not require the Python or Swift test suites.
