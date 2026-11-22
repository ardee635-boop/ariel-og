# ============================================================
# NIFLHEIM — router/registration.py
# .start now just links to the site — actual trainer creation
# (starter roll, items, quest) happens via the site's Starter
# Reveal page, see router/site_actions.py:handle_grant_starter
# and index.js's /api/player/grant-starter route.
# ============================================================


class RegistrationMixin:

    def _start(self, sender, push_name=None):
        # Already registered
        if self.db.exists(sender):
            player = self._get(sender)
            return (
                f"Welcome back, {player.name}.\n"
                "_Use 1 2 3 4 to move._"
            )

        return (
            "❄️ *Welcome to Niflheim.*\n\n"
            "Please register on the site to begin your adventure:\n"
            "https://ariel-og.vercel.app/"
        )

    def _render_zone_map(self, sender, player):
        from map import render_minimap
        return render_minimap(player)

