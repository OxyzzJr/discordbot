import discord
from typing import List


class PaginationView(discord.ui.View):
    """Vue de pagination avec boutons Précédent / Suivant."""

    def __init__(self, embeds: List[discord.Embed], author_id: int = None, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.current = 0
        self.message: discord.Message = None
        self._sync_buttons()

    def _sync_buttons(self):
        total = len(self.embeds)
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= total - 1
        for embed in self.embeds:
            embed.set_footer(text=f"Page {self.current + 1}/{total}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Vous ne pouvez pas utiliser ces boutons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


class ConfirmView(discord.ui.View):
    """Vue de confirmation avec boutons Confirmer / Annuler."""

    def __init__(self, author_id: int, timeout: int = 30):
        super().__init__(timeout=timeout)
        self.value: bool | None = None
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Cette confirmation ne vous appartient pas.", ephemeral=True)
            return False
        return True

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()


def build_pages(entries: list, title: str, color: int,
                per_page: int = 5, entry_formatter=None) -> List[discord.Embed]:
    """
    Découpe `entries` en pages d'embeds.
    `entry_formatter(i, entry) -> (name, value)` construit chaque field.
    """
    pages = []
    for start in range(0, max(len(entries), 1), per_page):
        chunk = entries[start:start + per_page]
        embed = discord.Embed(title=title, color=color)
        for i, entry in enumerate(chunk, start + 1):
            if entry_formatter:
                name, value = entry_formatter(i, entry)
                embed.add_field(name=name, value=value, inline=False)
        pages.append(embed)
    return pages
