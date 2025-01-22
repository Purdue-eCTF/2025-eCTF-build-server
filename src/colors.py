import colorama


def blue(s):
    return colorama.Fore.BLUE + s + colorama.Fore.RESET


def red(s):
    return colorama.Fore.RED + s + colorama.Fore.RESET
