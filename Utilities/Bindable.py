from typing import Callable,  Optional

class Bindable[T]:
    valueChangedCallbacks: list[Callable[[T | None, T], None]] = []
    value : Optional[T] = None

    def onValueChanged(self, callback: Callable[[T | None, T], None]):
        self.valueChangedCallbacks.append(callback)
        pass

    def set(self, newValue : T):
        if(self.value == newValue):
            return
        
        for callback in self.valueChangedCallbacks:
            callback(self.value, newValue)

        self.value = newValue

    def getNonNullValue(self) -> T:
        if(self.value is not None):
            return self.value
        
        raise TypeError


    def hasValue(self):
        return self.value is not None
        
