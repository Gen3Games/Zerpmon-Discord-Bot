import asyncio
import os

import nextcord
from PIL import Image
from nextcord import Message, Embed, File
import config
import db_query


class CustomEmbed(Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


def gen_image(_id, path1, path3, path2='./static/rank_images/arrow.png'):
    bg_img = Image.new("RGBA", (1440, 720), color='black')

    img1 = Image.open(path1)
    img2 = Image.open(path2)
    img2 = img2.convert("RGBA")
    img3 = Image.open(path3)

    img1 = img1.resize((600, 600))
    img2 = img2.resize((200, 150))
    img3 = img3.resize((600, 600))

    # Create a new RGBA image with the size of the background image
    combined_img = Image.new('RGBA', bg_img.size, (0, 0, 0, 0))

    # Paste the background image onto the new image
    combined_img.paste(bg_img, (0, 0))

    # Paste the three images onto the new image
    combined_img.paste(img1, (10, 50), mask=img1)  # adjust the coordinates as needed
    combined_img.paste(img2, (600, 300), mask=img2)
    combined_img.paste(img3, (800, 50), mask=img3)

    # Resize the combined image to be 50% of its original size

    # Save the final image
    combined_img.save(f'{_id}.png', quality=50)


async def send_last_embed(user: nextcord.Member, oppo: nextcord.Member, msg: Message, battle_instance, winner, b_type, mode='rank'):
    points1, t1, new_rank1 = db_query.update_rank(battle_instance["challenger"],
                                                  True if winner == 1 else False,
                                                  field='rank5' if b_type == 5 else 'rank')
    points2, t2, new_rank2 = db_query.update_rank(battle_instance["challenged"],
                                                  None if mode == 'rank5' else (True if winner == 2 else False),
                                                  field='rank5' if b_type == 5 else 'rank')
    embed = CustomEmbed(title="Match Result", colour=0xfacf5a,
                        description=f"{battle_instance['username1']}vs{battle_instance['username2']}")
    if new_rank1 is not None:
        await user.add_roles(config.RANKS[new_rank1]['role'])
        rm_role = [v for r, v in config.RANKS.items() if v['h'] > abs(t1['points'] - 1000) >= v['l']]
        if len(rm_role) > 0:
            await user.remove_roles(rm_role[0]['role'])
    if new_rank2 is not None:
        if oppo is None:
            oppo = await msg.guild.fetch_member(battle_instance['challenged'])
        await oppo.add_roles(config.RANKS[new_rank2]['role'])
        rm_role = [v for r, v in config.RANKS.items() if v['h'] > abs(t2['points'] - 1000) >= v['l']]
        if len(rm_role) > 0:
            await oppo.remove_roles(rm_role[0]['role'])
    img_rf, rf = new_rank1 if new_rank1 is not None else new_rank2, t1 if new_rank1 is not None else t2
    img_ri = [r for r, v in config.RANKS.items() if v['h'] > abs(rf['points'] - 1000) >= v['l']][0]
    if img_rf is not None:
        gen_image(msg.id, f'./static/rank_images/{img_ri}.png', f'./static/rank_images/{img_rf}.png')
    embed.add_field(name='\u200B', value='\u200B')
    embed.add_field(name='🏆 WINNER 🏆',
                    value=battle_instance['username1'] if winner == 1 else battle_instance[
                        'username2'],
                    inline=False)
    embed.add_field(
        name=f"{t1['tier'] if winner == 1 else t2['tier']} {'⭐ Rank Up `⬆` ⭐' if (new_rank1 if winner == 1 else new_rank2) is not None else ''}",
        value=f"{t1['points'] if winner == 1 else t2['points']}  {'⬆' if winner == 1 or mode =='rank' else ''}",
        inline=False)
    embed.add_field(name=f'ZP:\t+{points1 if winner == 1 else points2}', value='\u200B',
                    inline=False)
    embed.add_field(name='\u200B', value='\u200B')
    embed.add_field(name='💀 LOSER 💀',
                    value=battle_instance['username1'] if winner == 2 else battle_instance[
                        'username2'], inline=False)
    loser_p = points1 if winner == 2 else points2
    embed.add_field(
        name=f"{t1['tier'] if winner == 2 else t2['tier']} {('🤡 Rank Down `⬇` 🤡' if loser_p > 0 else '⭐ Rank Up `⬆` ⭐') if (new_rank1 if winner == 2 else new_rank2) is not None else ''}",
        value=f"{t1['points'] if winner == 2 else t2['points']} {'' if mode == 'rank5' and winner == 1 else ('⬇' if loser_p > 0 else '⬆')}",
        inline=False)
    embed.add_field(name=f'ZP:\t{"-" if loser_p > 0 else "+"}{abs(loser_p)} {"Ghost Battle" if mode == "rank5" else ""}', value='\u200B',
                    inline=False)
    file = None
    if img_rf is not None:
        file = File(f"{msg.id}.png", filename="image.png")
        embed.set_image(url=f'attachment://image.png')
    await msg.reply(embed=embed, file=file)
    if img_rf is not None:
        file.close()
        for i in range(3):
            try:
                os.remove(f"{msg.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")
                await asyncio.sleep(1)
