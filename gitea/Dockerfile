FROM gitea/gitea:1.22-rootless

# ── Thin overlay: vanilla Gitea + SCADA Studio custom templates ──
# To upgrade Gitea, just bump the tag above and rebuild.
# Templates inject a toolbar and per-file SCADA buttons into the UI.

COPY gitea/custom/templates/custom/ /var/lib/gitea/custom/templates/custom/

# Railway sets PORT dynamically; pass it through to Gitea
# (Gitea reads GITEA__server__HTTP_PORT from env, set via Railway variables)
