# GitHub Secrets Setup Guide

## 🔐 Required Secrets for CI/CD

This repository requires the following secrets to be configured in GitHub Actions.

---

## Step-by-Step Setup

### 1. Navigate to Repository Settings

1. Go to your repository on GitHub
2. Click **Settings** (top right)
3. In the left sidebar, click **Secrets and variables** → **Actions**

**Direct URL:**
```
https://github.com/YOUR_USERNAME/liquidity-crunch-monitor/settings/secrets/actions
```

---

### 2. Add DB_PASSWORD Secret

Click **New repository secret** and configure:

| Field | Value |
|-------|-------|
| **Name** | `DB_PASSWORD` |
| **Secret** | Your PostgreSQL password for CI/CD tests |

**For CI/CD Testing:**
```
# You can use a test password for CI/CD (not production!)
DB_PASSWORD = "test_ci_password_2026"
```

**Click "Add secret"**

---

### 3. Verify Secrets are Set

After adding, you should see:

```
✅ DB_PASSWORD (Updated X minutes ago)
```

---

## 🧪 Local Testing with `act`

To test GitHub Actions locally with `act`, you need to provide secrets:

### Method 1: Command Line (Quick Test)

```bash
# Test with inline secret
act push -s DB_PASSWORD="test_password"

# Test specific job
act -j test -s DB_PASSWORD="test_password"
```

### Method 2: Secrets File (Recommended)

Create `.secrets` file (already in `.gitignore`):

```bash
# Create secrets file for act
cat > .secrets << 'EOF'
DB_PASSWORD=test_local_password
EOF
```

Run act with secrets file:
```bash
# act will automatically use .secrets file
act push

# Or explicitly specify
act push --secret-file .secrets
```

---

## 📋 Complete Secret Checklist

### Required Secrets

- [x] `DB_PASSWORD` - PostgreSQL database password for tests

### Optional Secrets (if using authenticated APIs)

- [ ] `BINANCE_API_KEY` - Binance API key (optional)
- [ ] `BINANCE_API_SECRET` - Binance API secret (optional)
- [ ] `CODECOV_TOKEN` - Codecov upload token (optional, public repos don't need)

---

## 🔍 Verify Setup

### Test with `act` (Local)

```bash
# Full workflow test
make act-all

# Or manually
act push -s DB_PASSWORD="test_password"
```

**Expected output:**
```
✅ Test Suite (Python 3.10)
✅ Test Suite (Python 3.11)
✅ Test Suite (Python 3.12)
✅ Type Checking
✅ Linting
```

### Test on GitHub (Remote)

```bash
# Push to trigger CI
git push origin main
```

Go to:
```
https://github.com/YOUR_USERNAME/liquidity-crunch-monitor/actions
```

**Expected:** All workflows show green checkmarks ✅

---

## ⚠️ Security Best Practices

### DO ✅

- Use separate passwords for:
  - **Local development** (`.env.local`)
  - **CI/CD testing** (GitHub Secrets)
  - **Production** (AWS Secrets Manager / Vault)

- Use strong, random passwords for production:
  ```bash
  openssl rand -base64 30
  ```

- Rotate secrets regularly (every 90 days)

### DON'T ❌

- ❌ Don't use production passwords in CI/CD
- ❌ Don't commit `.env` or `.secrets` files
- ❌ Don't hardcode passwords in workflow files
- ❌ Don't share secrets in Slack/email

---

## 🆘 Troubleshooting

### Error: "DB_PASSWORD environment variable is not set"

**Cause:** Secret not configured in GitHub

**Fix:**
1. Go to Repository Settings → Secrets → Actions
2. Add `DB_PASSWORD` secret
3. Re-run failed workflow

### Error: "Bad credentials" in workflow

**Cause:** Typo in secret name

**Fix:**
1. Verify secret name is exactly `DB_PASSWORD` (case-sensitive)
2. Check workflow file uses `${{ secrets.DB_PASSWORD }}`

### `act` fails with "secret not found"

**Cause:** No `.secrets` file or missing `-s` flag

**Fix:**
```bash
# Use -s flag
act push -s DB_PASSWORD="test_password"

# Or create .secrets file
echo "DB_PASSWORD=test_password" > .secrets
act push
```

---

## 📚 References

- [GitHub: Encrypted secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [nektos/act: Running with secrets](https://github.com/nektos/act#secrets)
- [12-Factor App: Config](https://12factor.net/config)
