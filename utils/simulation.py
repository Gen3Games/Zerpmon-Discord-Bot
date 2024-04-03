from nextcord import Interaction, ui
import db_query
from globals import CustomEmbed


async def simulation_callback(interaction: Interaction, battle_count: int, playerA: dict, playerB: dict):
    embed = CustomEmbed(title=f"Simulation Results")
    uid = db_query.make_sim_battle_req(playerA, playerB, cnt=battle_count)
    await interaction.send(embeds=[embed])
