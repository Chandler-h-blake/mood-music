# Security Policy

## Supported version

Security fixes currently target the latest code on `main`.

## Reporting a vulnerability

Please use GitHub's private security advisory form instead of a public issue. Include a minimal reproduction, affected version, and impact, but never include a real QQ Music cookie, model API key, private library export, or other personal data.

Until the repository owner enables GitHub Security Advisories, contact the owner privately through their GitHub profile.

## Local security model

MoodMusic is a single-user local application. The API listens on `127.0.0.1` by default, and credentials use the current Windows user's protected credential storage. Do not expose the API directly to a public network or share the local data directory between accounts.
