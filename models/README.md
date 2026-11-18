# models/

Local model weights live here, mounted read-only into the API and workers at
`/models`. Only `registry.yaml` and this README are tracked in git.
Install weights with `scripts/fetch_models.md`; a file is used only if its
SHA-256 matches `registry.yaml`.
