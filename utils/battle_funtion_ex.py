import re
from nextcord import File
import config
import db_query
from utils.checks import CustomEmbed, gen_image


async def get_zerp_battle_embed_ex(message, z1_equipped, z2_equipped, moves, buffed_zerp1, buffed_zerp2,
                                   extra_buffs, hp=None):
    z1_obj, z2_obj = z1_equipped['zerpmon'], z2_equipped['zerpmon']
    z1_eq, z2_eq = z1_equipped['equipment'] if z1_equipped['equipment'] else {}, \
                   z2_equipped['equipment'] if z2_equipped['equipment'] else {}
    z1_moves = moves['A']
    z2_moves = moves['B']

    w_candy1, g_candy1, lvl_candy1 = z1_obj.get('white_candy') or 0, z1_obj.get('gold_candy') or 0, z1_obj.get(
        'licorice') or 0
    w_candy2, g_candy2, lvl_candy2 = z2_obj.get('white_candy') or 0, z2_obj.get('gold_candy') or 0, z2_obj.get(
        'licorice') or 0
    eq1_effect_list = z1_eq.get('notes', [])
    eq2_effect_list = z2_eq.get('notes', [])
    eq2_note2 = None
    if 'equipment2' in extra_buffs:
        eq2_note2 = await db_query.get_eq_by_name(extra_buffs['equipment2'])
        for i in eq2_note2['notes']:
            eq2_effect_list.append(i.lower())

    main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x35bcbf)
    z1_asc = z1_obj.get("ascended", False)
    z2_asc = z2_obj.get("ascended", False)

    main_embed.add_field(
        name=f"{z1_obj['displayName']} ({', '.join(z1_obj['zerpmonType'])})\t`{w_candy1}x🍬\t{g_candy1}x🍭`\t" + (
            f' (**Ascended** ☄️)' if z1_asc else ''),
        value=f"{config.TYPE_MAPPING[buffed_zerp1.title()]} **Trainer buff**" if buffed_zerp1 else "\u200B",
        inline=False)
    if z1_eq != {}:
        main_embed.add_field(
            name=f"{config.TYPE_MAPPING[z1_eq.get('type')]} Equipment",
            value=f"{z1_eq['name']}:\n" + '\n'.join([f"`{i}`" for i in eq1_effect_list]),
            inline=False)

    for i, move in enumerate(z1_moves):
        notes = f"{(await db_query.get_move(move['name'], move.get('stars', 0)))['notes']}" if move['color'] == 'purple' else ''
        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if move['dmg'] else "") + \
                  (f"> Stars: {move['stars'] * '★'}\n" if move.get('stars') else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type']]}\n" if move.get('type') else "") + \
                  f"> Percentage: {round(move['percent'], 1)}%\n",
            inline=True)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)
    main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)

    main_embed.add_field(
        name=f"{z2_obj['displayName']} ({', '.join(z1_obj['zerpmonType'])})\t`{w_candy2}x🍬\t{g_candy2}x🍭`\t" + (
            f' (**Ascended** ☄️)' if z2_asc else ''),
        value=f"{config.TYPE_MAPPING[buffed_zerp2.title()]} **Trainer buff**" if buffed_zerp2 else "\u200B",
        inline=False)
    if z2_eq != {}:
        main_embed.add_field(
            name=f"{config.TYPE_MAPPING[z2_eq.get('type')]} Equipment",
            value=f"{z2_eq['name']}:\n" + '\n'.join([f"`{i}`" for i in z2_eq['notes']]),
            inline=False)
        if eq2_note2:
            main_embed.add_field(
                name=f"{config.TYPE_MAPPING[eq2_note2.get('type')]} Equipment",
                value=f"{eq2_note2['name']}:\n" + '\n'.join([f"`{i}`" for i in eq2_note2['notes']]),
                inline=False)
    for i, move in enumerate(z2_moves):
        notes = f"{(await db_query.get_move(move['name'], stars=move.get('stars', 0)))['notes']}" if move['color'] == 'purple' else ''
        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if move['dmg'] else "") + \
                  (f"> Stars: {move['stars'] * '★'}\n" if move.get('stars') else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type']]}\n" if move.get('type') else "") + \
                  f"> Percentage: {round(move['percent'], 1)}%\n",
            inline=True)
    if hp is not None:
        main_embed.add_field(
            name=f"**HP 💚:**",
            value=f"> **{hp}**",
            inline=True)

    file = File(f"{message.id}.png", filename="image.png")
    main_embed.set_image(url=f'attachment://image.png')
    z1_obj['applied'] = True
    z2_obj['applied'] = True
    return main_embed, file


async def generate_image_ex(_id, z1_equipped, z2_equipped, gym_bg):
    z1_obj, z2_obj = z1_equipped['zerpmon'], z2_equipped['zerpmon']
    z1_eq, z2_eq = z1_equipped['equipment']['name'] if z1_equipped['equipment'] else {}, \
                   z2_equipped['equipment']['name'] if z2_equipped['equipment'] else {}
    path1 = f"./static/images/{z1_obj['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{z2_obj['name']}.png"
    zimg1 = z1_obj['image']
    zimg2 = z2_obj['image']
    z1_asc = z1_obj.get("ascended", False)
    z2_asc = z2_obj.get("ascended", False)

    url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
    url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
    await gen_image(_id, url1, url2, path1, path2, path3, gym_bg=gym_bg, eq1=z1_eq,
                    eq2=z2_eq, zerp_ascension=[z1_asc, z2_asc] if z1_asc or z2_asc else None)