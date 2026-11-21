def rupees(paise: int) -> str:
    whole, fraction = divmod(abs(paise), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = [head[max(0, i - 2) : i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join([*groups, tail])
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{digits}" + (f".{fraction:02d}" if fraction else "")
