import re

LOG_FORMATS = {
    "Apache": r"\[<Time>\] \[<Level>\] <Content>",
    "HDFS": r"<Date> <Time> <Pid> <Level> <Component>: <Content>",
    "Hadoop": r"<Date> <Time> <Level> \[<Process>\] <Component>: <Content>",
    "Spark": r"<Date> <Time> <Level> <Component>: <Content>",
    "Zookeeper": r"<Date> <Time> - <Level>  \[<Node>:<Component>@<Id>\] - <Content>",
    "OpenStack": r"<Logrecord> <Date> <Time> <Pid> <Level> <Component> \[<ADDR>\] <Content>",
    "Linux": r"<Month> <Date> <Time> <Level> <Component>(\[<PID>\])?: <Content>",
    "OpenSSH": r"<Date> <Day> <Time> <Component> sshd\[<Pid>\]: <Content>",
}

FIELD = re.compile(r"<([A-Za-z]+)>")
WILDCARD = "<*>"


def header_pattern_of(log_format: str) -> re.Pattern:
    pieces = FIELD.split(log_format)
    regex = ""
    for position, piece in enumerate(pieces):
        if position % 2 == 0:
            regex += re.sub(" +", r"\\s+", piece)
        else:
            regex += f"(?P<{piece}>.*?)"
    return re.compile(f"^{regex}$")


def template_pattern_of(template: str) -> re.Pattern:
    literal_pieces = [re.escape(piece).replace(r"\ ", r"\s+") for piece in template.split(WILDCARD)]
    return re.compile("(.*?)".join(literal_pieces))
