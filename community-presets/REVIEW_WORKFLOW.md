# Community Preset Review Workflow

Use this workflow when a user submits a preset through the controller UI's
`Submit Preset` action.

## Submission Source

The controller opens a GitHub issue draft with:

- title: `Community preset: <name>`
- lamp model
- use case
- reviewer/user notes
- preset JSON in a fenced `json` block

Example issue:

```text
Community preset: Iridescence Viewing
```

## Review Checklist

1. Confirm the issue contains one preset JSON block.
2. Confirm the JSON is preset-only, not a controller backup.
3. Required fields:
   - `kind`: `k7_community_preset`
   - `schema`: `1`
   - `lamp`: `k7mini` or `k7pro`
   - `name`
   - `use_case`
   - `notes`
   - `manual`
   - `schedule`
4. Confirm `manual` has enough active channels:
   - K7 Mini: at least 3 values
   - K7 Pro: at least 6 values
5. Confirm `schedule` has exactly 24 rows.
6. Confirm every schedule row has at least 8 values:
   - hour
   - minute
   - six channel values
7. Confirm values are numeric and in the expected 0-100 range.
8. Confirm the notes do not make unsafe or over-certain claims.
9. Confirm suitability/PAR/umol claims are caveated unless directly measured.
10. Prefer concise names and use cases that will make sense in the public page.

## Adding A Reviewed Preset

Save the reviewed JSON as a file under:

```text
community-presets/reviewed/
```

Use a lower-case, underscore-separated filename, for example:

```text
community-presets/reviewed/iridescence_viewing_k7mini.json
```

Do not manually edit the generated public index or embedded page data.

## Regenerating The Public Page

Run:

```bash
python3 tools/generate_public_profiles.py
```

This regenerates:

```text
community-presets/index.json
website/community-presets/index.json
website/community-presets.html
```

The generator includes:

- built-in profiles from `arduino/src/Presets.h`
- reviewed community profiles from `community-presets/reviewed/*.json`

## Validation Commands

Check total profile counts:

```bash
jq '.presets | length' community-presets/index.json
jq '.presets | map(select(.source=="built-in")) | length' community-presets/index.json
jq '.presets | map(select(.source=="community")) | length' community-presets/index.json
```

Check reviewed community entries:

```bash
jq '[.presets[] | select(.source=="community") | {name,lamp,use_case,manual:.preset.manual,peak:.preset.schedule[12]}]' community-presets/index.json
```

Check the embedded fallback index in the HTML:

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('website/community-presets.html','utf8'); const m=html.match(/<script type=\"application\\/json\" id=\"embeddedPresetIndex\">\\n([\\s\\S]*?)\\n\\s*<\\/script>/); if(!m) throw new Error('no embedded index'); const idx=JSON.parse(m[1]); console.log(idx.presets.length);"
```

Search for the profile in all generated outputs:

```bash
rg -n "<Preset Name>|<distinct notes text>" community-presets/index.json website/community-presets/index.json website/community-presets.html
```

## Commit And Deploy

Stage:

```bash
git add community-presets/index.json community-presets/reviewed/<file>.json tools/generate_public_profiles.py website/community-presets.html website/community-presets/index.json
```

If `tools/generate_public_profiles.py` was not changed, omit it from the staged
paths.

Commit:

```bash
git commit -m "Add reviewed <name> preset"
```

Push:

```bash
git push origin master
```

Watch the Pages deploy:

```bash
gh run list --workflow "Deploy GitHub Pages" --limit 3
gh run watch <run-id> --exit-status
```

## Live Verification

Check the live index:

```bash
curl -L --fail --silent --show-error \
  "https://bitbarista.github.io/k7-led-controller/community-presets/index.json?verify=<commit>" \
  | jq '[.presets[] | select(.source=="community") | {name,lamp,use_case,manual:.preset.manual,peak:.preset.schedule[12]}]'
```

Check the live page contains the profile:

```bash
curl -L --fail --silent --show-error \
  "https://bitbarista.github.io/k7-led-controller/community-presets.html?verify=<commit>" \
  | rg "<Preset Name>|Community K7 Mini Profiles|Community K7 Pro Profiles"
```

## Closing The Submission

After live verification, comment on the GitHub issue:

```text
Reviewed and published in commit <commit>. The preset is now listed under
Community K7 Mini Profiles / Community K7 Pro Profiles on the public profiles page.
```

Then close the issue:

```bash
gh issue close <issue-number> --repo bitbarista/k7-led-controller --comment "Closing as reviewed and published."
```

If the preset is rejected or needs changes, leave the issue open and comment
with the requested changes instead.
