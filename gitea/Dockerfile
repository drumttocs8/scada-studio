FROM gitea/gitea:1.22-rootless

# ── Thin overlay: vanilla Gitea + SCADA Studio custom templates ──
# To upgrade Gitea, just bump the tag above and rebuild.
# Templates inject a toolbar and per-file SCADA buttons into the UI.
#
# Build context is gitea/ (Railway Root Directory = gitea/)

COPY custom/templates/custom/ /var/lib/gitea/custom/templates/custom/
