"""Utility functions for the pipeline runner"""

import typer
import questionary
from typing import List

def checkbox_filter(
    items: List[str],
    message: str = "Select items:",
    allow_empty: bool = True,
    invert_selections: bool = False
) -> List[str]:
    """
    Show a checkbox interface and return the filtered list of selected items.
    
    Args:
        items: List of strings to choose from
        message: Prompt message to display
        pre_selected: List of items that should be pre-selected
        allow_empty: Whether to allow empty selection (if False, forces at least one selection)
        invert_selections: Whether to return the opposite of selection (if True, return only items that arent selcetd)
    
    Returns:
        List of selected items (empty list if nothing selected or user cancelled)
    """
    if not items:
        typer.echo("No items to select from!")
        return []
    
    
    while True:
        selected = questionary.checkbox(
            message,
            choices=items,
        ).ask()
        
        # Handle user cancellation (Ctrl+C or ESC)
        if selected is None:
            typer.echo("Selection cancelled!")
            return []
        
        # Check if empty selection is allowed
        if not selected and not allow_empty:
            typer.echo("⚠️  You must select at least one item!")
            continue
        
        if invert_selections:
            selected = [item for item in items if item not in selected]
        return selected


def select_from_list(
    items: List[str],
    message: str = "Select an item:",
) -> str:
    """
    Show a selection interface and return the selected item.
    
    Args:
        items: List of strings to choose from
        message: Prompt message to display
    
    Returns:
        Selected item string, or None if cancelled
    """
    if not items:
        typer.echo("No items to select from!")
        return None
    
    selected = questionary.select(
        message,
        choices=items,
    ).ask()
    
    return selected
