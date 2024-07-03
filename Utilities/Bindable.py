from typing import Callable, Optional


class Bindable[T]:
    def __init__(self) -> None:
        self.value: Optional[T] = None
        self.valueChangedCallbacks: list[Callable[[T | None, T | None], None]]
        self.valueChangedCallbacks = []

    def onValueChanged(self, callback: Callable[[T | None, T | None], None]):
        self.valueChangedCallbacks.append(callback)
        pass

    def set(self, newValue: T | None):
        if self.value == newValue:
            return

        for callback in self.valueChangedCallbacks:
            callback(self.value, newValue)

        self.value = newValue

    def getNonNullValue(self) -> T:
        if self.value is not None:
            return self.value

        raise TypeError

    def hasValue(self):
        return self.value is not None
