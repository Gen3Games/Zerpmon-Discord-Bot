import db_query
import pandas as pd


def save_wr():
    data = []
    df = pd.DataFrame(columns=['Zerpmon', 'Total Matches', 'Winrate'])
    for document in db_query.get_all_z():
        if 'total' in document:
            data.append({'Zerpmon': document['name'], 'Total Matches': document['total'],
                         'Winrate': round(document['winrate'], 2)})
        else:
            data.append({'Zerpmon': document['name'], 'Total Matches': 0, 'Winrate': 0})

    df = pd.concat([df, pd.DataFrame(data)], ignore_index=True)

    print(df)
    df.to_excel("winrates.xlsx", index=False, header=True)


def save_ranks():
    data = []
    df = pd.DataFrame(columns=['User', 'Discord_Id', 'Rank', 'Points'])
    for document in db_query.get_all_users():
        if 'rank' in document:
            data.append({'User': document['username'], 'Discord_Id': document['discord_id'],
                         'Rank': document['rank']['tier'], 'Points': document['rank']['points']})
        else:
            data.append({'User': document['username'], 'Discord_Id': document['discord_id'], 'Rank': 'Unranked', 'Points': 0})

    df = pd.concat([df, pd.DataFrame(data)], ignore_index=True)

    print(df)
    df.to_excel("rankings.xlsx", index=False, header=True)

save_ranks()