from nextcord import Embed
import config


class CustomEmbed(Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url='https://cdn.discordapp.com/avatars/1093248198480498800/e6560ac61e8c847088704715dcaaf0bc.webp?size=100')