from typing import MutableSequence


def removeIfExist(list: MutableSequence, item):
    if item in list:
        list.remove(item)


def appendIfNotExist(list: MutableSequence, item):
    if item in list:
        return

    list.append(item)
