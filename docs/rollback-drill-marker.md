# Production rollback drill marker

This harmless documentation-only change exists solely to exercise the guarded
post-deployment rollback path. The production verifier intentionally fails when
the deployed commit message contains `[rollback-drill]`; the rollback workflow
must then revert this file, pass the protected quality gate, fast-forward
`main`, redeploy through Dokploy, and re-run production verification.
