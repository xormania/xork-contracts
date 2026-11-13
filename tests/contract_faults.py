"""Deliberate resolver defects; each is otherwise the healthy reference adapter."""

from xcontracts.model import OrchestrationError
from xcontracts.testing.fakes import MemoryContractResolver


class WrongVersionResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        result = super().resolve(contract_id, version)
        if result is not None:
            result["version"] = "silently-selected-other-version"
        return result


class MissingAsEmptyResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        result = super().resolve(contract_id, version)
        return {} if result is None else result


class DroppedArtifactsResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        result = super().resolve(contract_id, version)
        if result is not None:
            result.pop("artifacts", None)
        return result


class SharedDefinitionResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        super().resolve(contract_id, version)  # retain argument/lifetime validation
        return self._definitions.get((contract_id, version))


class ShallowDefinitionResolver(SharedDefinitionResolver):
    def resolve(self, contract_id, version):
        result = super().resolve(contract_id, version)
        return result.copy() if result is not None else None


class InvalidReferenceMissingResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        if any(type(value) is not str or not value for value in (contract_id, version)):
            return None
        return super().resolve(contract_id, version)


class ReusableContractResolver(MemoryContractResolver):
    def close(self):
        pass


class OneSidedResolver(MemoryContractResolver):
    def resolve(self, contract_id, version):
        result = super().resolve(contract_id, version)
        if result is not None:
            result["roles"].pop(next(iter(result["roles"])))
        return result


class KnownFailureResolver(MemoryContractResolver):
    """Healthy control with an independently established backend failure."""

    def __init__(self, code):
        super().__init__([])
        self.failure_code = code

    def resolve(self, contract_id, version):
        super().resolve(contract_id, version)
        raise OrchestrationError("The backend fixture is in a known failure state.", self.failure_code)


class FailureAsAbsenceResolver(KnownFailureResolver):
    def resolve(self, contract_id, version):
        return None


class FailureAsSuccessResolver(KnownFailureResolver):
    def resolve(self, contract_id, version):
        return {
            "schema_version": "1", "id": contract_id, "version": version,
            "roles": {
                "sender": {"obligations": ["Send a value."]},
                "receiver": {"obligations": ["Receive the value."]},
            },
        }


class WrongFailureCodeResolver(KnownFailureResolver):
    def resolve(self, contract_id, version):
        raise OrchestrationError("The fixture misclassifies its backend failure.", "invalid_arguments")
