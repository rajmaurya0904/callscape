def slugify(s):
    return s.lower()

def fmt(x):
    return str(x)

def log(msg):
    print(fmt(msg))


def fact(n):
    return 1 if n < 2 else n * fact(n - 1)


def is_even(n):
    return True if n == 0 else is_odd(n - 1)


def is_odd(n):
    return False if n == 0 else is_even(n - 1)
