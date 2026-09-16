# Contributing to MoodMusic

Thanks for helping make personal music libraries easier to rediscover.

## Start locally

MoodMusic targets Windows, Python 3.12–3.13, Node.js 22.13+, and Docker Desktop. To tour the UI without the backend:

```powershell
.\scripts\setup.ps1 -DemoOnly
.\scripts\start.ps1 -Demo
```

For development, run `.\scripts\setup.ps1` without `-DemoOnly`, then use `.\scripts\start.ps1` for the complete local stack and `.\scripts\stop.ps1` to stop the app processes. PostgreSQL remains running so local data is retained.

## Submit a change

1. Open an issue for substantial features or architecture changes.
2. Create a focused branch and keep commits reviewable.
3. Add or update tests and documentation with the implementation.
4. Run `.\scripts\test.ps1` before opening a pull request.
5. Explain user-visible behavior, limitations, and manual verification in the PR.

Never commit QQ Music cookies, model keys, real account data, copyrighted audio, playback URLs, `.env` files, or unsanitized logs. Contributions must not download protected audio, bypass membership/region/DRM restrictions, or expand private QQ Music API behavior beyond the documented read-only adapter boundary.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
