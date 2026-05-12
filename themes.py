THEMES = {
    'default': {
        'name': 'Padrão',
        'emoji': '✨',
        'description': 'Tema original do studio — dourado e marrom',
        'preview': '#C9A97A',
        'vars': {},
    },
    'primavera': {
        'name': 'Primavera',
        'emoji': '🌸',
        'description': 'Tons florais e rosados',
        'preview': '#D4879C',
        'vars': {
            '--gold':      '#D4879C',
            '--gold-dark': '#B5607A',
            '--cream':     '#FDF6F9',
            '--dark':      '#5C3D5E',
            '--mid':       '#8E6680',
            '--light':     '#F0DDE7',
        },
    },
    'verao': {
        'name': 'Verão',
        'emoji': '☀️',
        'description': 'Tons quentes de laranja e turquesa',
        'preview': '#E8965A',
        'vars': {
            '--gold':      '#E8965A',
            '--gold-dark': '#C4733A',
            '--cream':     '#FFF8F0',
            '--dark':      '#264653',
            '--mid':       '#4A7C8A',
            '--light':     '#C8E6ED',
        },
    },
    'outono': {
        'name': 'Outono',
        'emoji': '🍂',
        'description': 'Tons terrosos de ferrugem e ocre',
        'preview': '#D4694D',
        'vars': {
            '--gold':      '#D4694D',
            '--gold-dark': '#B04A30',
            '--cream':     '#FAF3EC',
            '--dark':      '#4A3728',
            '--mid':       '#7A5C48',
            '--light':     '#E8D5C4',
        },
    },
    'inverno': {
        'name': 'Inverno',
        'emoji': '❄️',
        'description': 'Tons frios de azul gelo e azul-marinho',
        'preview': '#7BA7BC',
        'vars': {
            '--gold':      '#7BA7BC',
            '--gold-dark': '#4A7D94',
            '--cream':     '#F5F8FA',
            '--dark':      '#1C2B3A',
            '--mid':       '#4A6880',
            '--light':     '#C8D8E8',
        },
    },
    'dia_da_mulher': {
        'name': 'Dia da Mulher',
        'emoji': '💜',
        'description': '8 de março — roxo e lilás',
        'preview': '#B5508C',
        'vars': {
            '--gold':      '#B5508C',
            '--gold-dark': '#8A2C6A',
            '--cream':     '#FDF5FF',
            '--dark':      '#4A1040',
            '--mid':       '#7A4C70',
            '--light':     '#EDD8ED',
        },
    },
    'dia_das_maes': {
        'name': 'Dia das Mães',
        'emoji': '💐',
        'description': 'Segundo domingo de maio — tons de rosa',
        'preview': '#E07B9E',
        'vars': {
            '--gold':      '#E07B9E',
            '--gold-dark': '#C05880',
            '--cream':     '#FFF5F8',
            '--dark':      '#5C2D40',
            '--mid':       '#8A5070',
            '--light':     '#F0D0DC',
        },
    },
    'namorados': {
        'name': 'Dia dos Namorados',
        'emoji': '❤️',
        'description': '12 de junho — rosa vibrante e vinho',
        'preview': '#E84393',
        'vars': {
            '--gold':      '#E84393',
            '--gold-dark': '#C01E70',
            '--cream':     '#FFF5F9',
            '--dark':      '#5C1030',
            '--mid':       '#8A3060',
            '--light':     '#F0C0D8',
        },
    },
    'natal': {
        'name': 'Natal',
        'emoji': '🎄',
        'description': '25 de dezembro — vermelho e verde',
        'preview': '#C41E3A',
        'vars': {
            '--gold':      '#C41E3A',
            '--gold-dark': '#9A1828',
            '--cream':     '#FFF9F9',
            '--dark':      '#1B5E20',
            '--mid':       '#4A8C50',
            '--light':     '#C8E6C9',
        },
    },
}


def get_theme_css(theme_key: str) -> str:
    theme = THEMES.get(theme_key, THEMES['default'])
    if not theme['vars']:
        return ''
    lines = [':root {']
    for k, v in theme['vars'].items():
        lines.append(f'  {k}: {v};')
    lines.append('}')
    return '\n'.join(lines)
