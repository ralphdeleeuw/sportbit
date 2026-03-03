# SportBit Auto Sign-Up

Automatically signs up for CrossFit Hilversum WOD classes via the SportBit API. Runs daily at midnight (Amsterdam time) through GitHub Actions.

Default schedule:
- **Monday** at 20:00
- **Wednesday** at 08:00
- **Thursday** at 20:00

## Setup

1. **Fork or clone this repo**

2. **Add your credentials as GitHub Actions secrets** (Settings > Secrets and variables > Actions > New repository secret):
   - `SPORTBIT_USERNAME` — your SportBit login email/username
   - `SPORTBIT_PASSWORD` — your SportBit password

   Or via CLI:
   ```bash
   gh secret set SPORTBIT_USERNAME
   gh secret set SPORTBIT_PASSWORD
   ```

3. **Test it** — go to the Actions tab > "CrossFit Auto Sign-Up" > "Run workflow" to trigger manually

The workflow runs every night at midnight and signs up for any scheduled classes in the next 7 days. If you're already signed up, it skips. Results are visible in the Actions log.

## Local usage

```bash
pip install requests

# Dry run (no sign-ups, just shows what it would do)
SPORTBIT_USERNAME=you@email.com SPORTBIT_PASSWORD=yourpass python3 autosignup.py

# Actually sign up
SPORTBIT_USERNAME=you@email.com SPORTBIT_PASSWORD=yourpass python3 autosignup.py --live
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--live` | off | Actually sign up (default is dry-run) |
| `--days N` | 7 | How many days to look ahead |
| `--username` | env var | SportBit username |
| `--password` | env var | SportBit password |

## Customization

To change the schedule, edit the `SCHEDULE` list at the top of `autosignup.py`:

```python
# Weekday numbers: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
SCHEDULE = [
    (0, "20:00"),  # Monday 20:00
    (2, "08:00"),  # Wednesday 08:00
    (3, "20:00"),  # Thursday 20:00
]
```
