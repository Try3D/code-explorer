# code-explorer

## Releasing to PyPI

Versioning is driven entirely by git tags via `hatch-vcs` — there is no version number in `pyproject.toml`.

After code review and merging to main, create and push a tag to trigger the GitHub Actions publish workflow:

```bash
git tag v1.0.2
git push origin v1.0.2
```

The workflow at `.github/workflows/publish.yml` will build and publish to PyPI automatically.

### Checklist before tagging
- [ ] All changes reviewed and merged to main
- [ ] Decide the next version (follow semver: patch for fixes, minor for features, major for breaking changes)
- [ ] Add `PYPI_API_TOKEN` secret in GitHub repo settings if not already set (Settings → Secrets → Actions)
