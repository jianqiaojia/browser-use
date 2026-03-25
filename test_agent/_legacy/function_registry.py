"""Function registry and execution for test automation.

This module provides functionality to register and execute predefined functions
that can be called before test case execution.

Example usage in test case:
{
    "prerun_calls": [
        {
            "function": "edit_group_policy",
            "parameters": {
                "policy_path": "Computer Configuration\\Administrative Templates\\Microsoft Edge",
                "policy_name": "Enable saving passwords to the password manager",
                "value_data": 1
            }
        }
    ]
}
"""
from typing import Any, Dict, Callable, List, Optional, Union
from test_agent.view import PredefinedFunctionCall
import winreg

# Registry to store predefined functions
_function_registry: Dict[str, Callable] = {}

def register_predefined_function(name: str, func: Callable) -> None:
    """Register a predefined function that can be called before test execution.
    
    Args:
        name: Name of the function to register
        func: Function to register
    """
    _function_registry[name] = func

def execute_predefined_functions(func_calls: List[PredefinedFunctionCall]) -> List[Any]:
    """Execute a list of predefined functions with their parameters.
    
    Args:
        func_calls: List of function calls with their parameters
        
    Returns:
        List of results from each function execution
        
    Raises:
        ValueError: If any function is not registered
        RuntimeError: If function execution fails
    """
    results = []
    
    for func_call in func_calls:
        if func_call.function not in _function_registry:
            raise ValueError(f"Function '{func_call.function}' is not registered")
            
        func = _function_registry[func_call.function]
        params = func_call.parameters or {}
        
        try:
            result = func(**params)
            results.append(result)
        except Exception as e:
            raise RuntimeError(f"Error executing function '{func_call.function}': {str(e)}")
            
    return results

def initialize_predefined_functions() -> None:
    """Register all predefined functions.
    
    This function should be called once at startup to register all available
    predefined functions that can be used in test cases.
    """
	# Add your custom functions here
    # register_predefined_function("your_function", your_function)
    register_predefined_function("edit_group_policy", edit_group_policy)

# Predefined functions
def edit_group_policy(policy_path: str, policy_name: str, value_data: Union[str, int], value_type: str = 'REG_DWORD', delete_key: bool = False) -> bool:
    """Edit a Windows group policy setting.

    Args:
        policy_path: Path to the policy (e.g. "Computer Configuration\\Administrative Templates\\Microsoft Edge")
        policy_name: Name of the policy to modify
        value_data: Value to set
        value_type: Registry value type (default: REG_DWORD)
        delete_key: If True, deletes the specified key instead of setting a value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Map value type strings to winreg constants
        value_type_map = {
            "REG_DWORD": winreg.REG_DWORD,
            "REG_SZ": winreg.REG_SZ,
            "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
            "REG_MULTI_SZ": winreg.REG_MULTI_SZ,
            "REG_BINARY": winreg.REG_BINARY
        }
        group_policy_name_map = {
            "Enable saving passwords to the password manager": "PasswordManagerEnabled",
            "Allow users to be alerted if their passwords are found to be unsafe": "PasswordMonitorAllowed",
            "Enable Autofill for addresses" : "AutofillAddressEnabled",
            "Restrict the length of passwords that can be saved in the password Manager": "PasswordManagerRestrictLengthEnabled",
            "Enable component updates in Microsoft Edge": "ComponentUpdatesEnabled",
            "Force synchronization of browser data and do not show the sync consent prompt": "ForceSync",
            "Allow importing of saved passwords": "ImportSavedPasswords",
            "Enable Password reveal button": "PasswordRevealEnabled",
            "Disable synchronization of data using Microsoft sync services": "SyncDisabled",
            "Configures a setting that asks users to enter their device password while using password autofill": "PrimaryPasswordSettings",
            "Configure the list of types that are excluded from synchronization": "SyncTypesListDisabled",
            "Configure the list of types that are included for synchronization": "ForceSyncTypes",
            "Allow importing of autofill form data": "ImportAutofillFormData"
        }
        group_policy_poath_map = {
            "Computer Configuration\\Administrative Templates\\Microsoft Edge": "SOFTWARE\\Policies\\Microsoft\\Edge",
            "Computer Configuration\\Administrative Templates\\Microsoft Edge-Default Settings(User can override)": "SOFTWARE\\Policies\\Microsoft\\Edge\\Recommended"
        }

        root_key = winreg.HKEY_LOCAL_MACHINE
        policy_key = group_policy_poath_map.get(policy_path)
        
        if policy_key is None:
            raise ValueError(f"Unknown policy path: {policy_path}")

        # Open the key for writing
        key = winreg.OpenKey(root_key, policy_key, 0, winreg.KEY_SET_VALUE)

        policy_value_name = group_policy_name_map.get(policy_name)
        if policy_value_name is None:
            raise ValueError(f"Unknown policy name: {policy_name}")

        if delete_key:
            # Delete the registry value
            try:
                winreg.DeleteValue(key, policy_value_name)
            except FileNotFoundError:
                # Key doesn't exist, which is fine since we wanted to delete it
                pass
        else:
            # Set the registry value
            winreg.SetValueEx(
                key,
                policy_value_name,
                0,
                value_type_map.get(value_type, winreg.REG_DWORD),
                value_data
            )

        winreg.CloseKey(key)
        return True

    except Exception as e:
        raise RuntimeError(f"Failed to set group policy value: {str(e)}")

# Initialize functions when module is imported
initialize_predefined_functions()