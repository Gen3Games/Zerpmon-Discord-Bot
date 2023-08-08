import nextcord
from db_query import get_owned


async def zerpmon_autocomplete(interaction: nextcord.Interaction, item: str):
    user_owned = get_owned(interaction.user.id)
    params = interaction.data['options'][0]['options']
    main_type = ''
    # if params[1]['name'] == 'use_on':
    #     main_type = user_owned['equipments'][params[0]['value']]['attributes'][-1]['value']
    remove_items = [i['value'] for i in params if i['name'][0].isdigit()]
    print(interaction.data)
    cards = {k: v for k, v in user_owned['zerpmons'].items() if
             item.lower() in v['name'].lower() and k not in remove_items and
             (main_type == '' or main_type in [i['value'] for i in v['attributes'] if i['trait_type'] == 'Type'])}
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for k, v in cards.items():
            if len(choices) == 25:
                break
            choices[v['name']] = k
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)


async def equipment_autocomplete(interaction: nextcord.Interaction, item: str):
    user_owned = get_owned(interaction.user.id)
    params = interaction.data['options'][0]['options']
    remove_items = [i['value'] for i in params if i['name'][0].isdigit()]
    if user_owned is not None and 'equipments' in user_owned:
        choices = {i['name']: k for k, i in user_owned['equipments'].items() if item in i['name'] and k not in remove_items}
    else:
        choices = {}
    choices = dict(sorted(choices.items()))
    await interaction.response.send_autocomplete(choices)