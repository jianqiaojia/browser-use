"""
UIA Click Action - Use Windows UI Automation to click elements

This uses UIA Helper to perform real OS-level mouse clicks, which are
indistinguishable from manual user clicks. This bypasses all browser-level
detection mechanisms.
"""

import requests
from typing import Optional
from pydantic import BaseModel, Field
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.agent.views import ActionResult


class UIAClickAction(BaseModel):
	"""UIA click action that uses Windows UI Automation."""

	index: int = Field(
		description='DOM element index to click via UIA'
	)


async def execute_uia_click(
	params: UIAClickAction,
	browser_session: BrowserSession,
) -> ActionResult:
	"""
	Execute click using Windows UI Automation via UIA Helper.

	This performs a real OS-level mouse click that is indistinguishable from
	manual user interaction. Edge and website JavaScript will treat this as
	a genuine user click.

	Steps:
	1. Get element coordinates from browser
	2. Convert to screen coordinates
	3. Use UIA Helper to perform OS-level mouse click

	Args:
		params: Click parameters
		browser_session: Browser session for coordinate lookup

	Returns:
		ActionResult with success/error message
	"""
	index = params.index

	# Get element from browser_session
	element = await browser_session.get_dom_element_by_index(index)
	if not element:
		return ActionResult(
			error=f'Element with index {index} not found',
			include_in_memory=True,
			success=False
		)

	# Get browser page for JavaScript evaluation
	page = await browser_session.get_current_page()

	# Get element's viewport coordinates using JavaScript getBoundingClientRect()
	# This is much more reliable than CDP's getBoxModel for coordinate calculation
	element_id = element.attributes.get('id', '')
	element_name = element.attributes.get('name', '')

	# Build selector - prefer id, fallback to name attribute
	if element_id:
		selector = f'#{element_id}'
	elif element_name:
		selector = f'[name="{element_name}"]'
	else:
		return ActionResult(
			error='Element must have either id or name attribute for UIA click',
			include_in_memory=True,
			success=False
		)

	try:
		# Get both window info and element rect in one JavaScript evaluation
		js_data = await page.evaluate(f'''() => {{
			const element = document.querySelector('{selector}');
			if (!element) {{
				return {{ error: 'Element not found with selector: {selector}' }};
			}}

			const rect = element.getBoundingClientRect();

			return {{
				// Element viewport-relative coordinates
				rect: {{
					left: rect.left,
					top: rect.top,
					width: rect.width,
					height: rect.height,
					centerX: rect.left + rect.width / 2,
					centerY: rect.top + rect.height / 2
				}},
				// Window position on screen
				screenX: window.screenX,
				screenY: window.screenY,
				screenLeft: window.screenLeft,
				screenTop: window.screenTop,
				// Window dimensions
				outerHeight: window.outerHeight,
				innerHeight: window.innerHeight,
				outerWidth: window.outerWidth,
				innerWidth: window.innerWidth,
				// Page scroll position (for debugging - not used in calculation)
				scrollX: window.scrollX || window.pageXOffset || 0,
				scrollY: window.scrollY || window.pageYOffset || 0,
				// Screen info
				screenWidth: window.screen.width,
				screenHeight: window.screen.height,
				availWidth: window.screen.availWidth,
				availHeight: window.screen.availHeight,
				// DPI scaling
				devicePixelRatio: window.devicePixelRatio,
			}};
		}}''')

		# Check for errors
		if isinstance(js_data, dict) and 'error' in js_data:
			return ActionResult(
				error=js_data['error'],
				include_in_memory=True,
				success=False
			)

		# Parse if returned as string
		if isinstance(js_data, str):
			import json
			info = json.loads(js_data)
		else:
			info = js_data

		# Extract element rect (viewport-relative coordinates)
		# IMPORTANT: getBoundingClientRect() returns coordinates relative to the VISIBLE viewport
		# This means scroll position is already accounted for - the returned coordinates are
		# what you see on screen right now, not the element's position in the full document
		js_rect = info['rect']
		viewport_x = js_rect['centerX']
		viewport_y = js_rect['centerY']

		# Get scroll position for debugging (not needed for calculation since getBoundingClientRect is viewport-relative)
		scroll_x = float(info.get('scrollX', 0))
		scroll_y = float(info.get('scrollY', 0))

		# Extract window position
		# window.screenLeft/screenTop give the position of the OUTER window edge on screen
		window_x = float(info.get('screenLeft', info.get('screenX', 0)))
		window_y = float(info.get('screenTop', info.get('screenY', 0)))

		# Calculate chrome height (titlebar + address bar + toolbar)
		top_chrome_height = float(info['outerHeight']) - float(info['innerHeight'])

		# Convert viewport-relative coordinates to screen coordinates
		#
		# Key insight: getBoundingClientRect() gives coordinates relative to the VISIBLE viewport,
		# so we don't need to add/subtract scroll offsets. The element's position in the viewport
		# is exactly what we need.
		#
		# Formula:
		# screen_coord = window_position + chrome_offset + viewport_coord
		#
		# For maximized windows on Windows:
		# - screenLeft is typically -7 or -8 (border extends off-screen)
		# - The visible client area actually starts at abs(screenLeft) on screen
		# - screenTop is typically 0, then we add chrome height to get to client area

		if window_x < 0:
			# Maximized window: client area starts at abs(window_x) pixels from left edge of screen
			screen_x = int(abs(window_x) + viewport_x)
		else:
			# Non-maximized window: window_x is the actual position
			screen_x = int(window_x + viewport_x)

		# Y coordinate: add chrome height to get from outer window top to client area top
		screen_y = int(window_y + top_chrome_height + viewport_y)

	except Exception as e:
		return ActionResult(
			error=f'Failed to get window position: {str(e)}',
			include_in_memory=True,
			success=False
		)

	# Call UIA Helper to perform OS-level click
	try:
		# First, focus the element via JavaScript to prepare it for the click
		# This ensures Edge's autofill listeners are activated
		page = await browser_session.get_current_page()
		try:
			# Focus the element first
			await page.evaluate(f'''
				(function() {{
					const element = document.querySelector('#{element.attributes.get("id", "")}');
					if (element) {{
						element.focus();
						return true;
					}}
					return false;
				}})()
			''')
			# Small delay to let focus event propagate
			import asyncio
			await asyncio.sleep(0.2)
		except Exception as focus_error:
			print(f"Warning: Could not focus element via JS: {focus_error}")

		# Build element description for debugging
		tag = element.tag_name
		attrs = []
		if element.attributes.get('type'):
			attrs.append(f"type={element.attributes['type']}")
		if element.attributes.get('id'):
			attrs.append(f"id={element.attributes['id']}")
		if element.attributes.get('name'):
			attrs.append(f"name={element.attributes['name']}")
		attr_str = ' '.join(attrs) if attrs else ''

		# Debug info
		is_maximized = window_x < 0
		border_offset = abs(window_x) if is_maximized else 0

		debug_info = f'''
UIA Click Debug:
  Element: {tag} {attr_str}

  Viewport Coordinates (from getBoundingClientRect):
    Center: ({viewport_x:.1f}, {viewport_y:.1f})
    Full rect: {js_rect}
    NOTE: These are relative to VISIBLE viewport (scroll already accounted for)

  Window Info:
    Position: screenLeft={window_x:.1f}, screenTop={window_y:.1f}
    Is Maximized: {is_maximized} (detected from screenLeft < 0)
    Border Offset: {border_offset:.1f}
    Window size: outer=({info.get('outerWidth', 0):.1f}, {info.get('outerHeight', 0):.1f}), inner=({info.get('innerWidth', 0):.1f}, {info.get('innerHeight', 0):.1f})
    Screen size: {info.get('screenWidth', 0):.0f}x{info.get('screenHeight', 0):.0f}
    DPI scaling: {info.get('devicePixelRatio', 1):.2f}x
    Top chrome height: {top_chrome_height:.1f}
    Page scroll: ({scroll_x:.1f}, {scroll_y:.1f}) [for info only - not used in calculation]

  Calculation:
    {'Maximized window:' if is_maximized else 'Normal window:'}
    screen_x = {'abs(' + f'{window_x:.1f}' + ')' if is_maximized else f'{window_x:.1f}'} + {viewport_x:.1f} = {screen_x}
    screen_y = {window_y:.1f} + {top_chrome_height:.1f} + {viewport_y:.1f} = {screen_y}

  Result:
    Final screen coords: ({screen_x}, {screen_y})
'''
		print(debug_info)

		response = requests.post(
			'http://localhost:3333/uia/click_at_position',
			json={
				'x': screen_x,
				'y': screen_y
			},
			timeout=5
		)
		response.raise_for_status()
		result = response.json()

		if result.get('success'):
			msg = f'✅ UIA clicked: {tag} {attr_str} at screen ({screen_x}, {screen_y}) [viewport: ({viewport_x:.1f}, {viewport_y:.1f})]'

			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
			)
		else:
			error = result.get('error', 'Unknown error')
			return ActionResult(
				error=f'❌ UIA click failed: {error}',
				include_in_memory=True,
				success=False
			)

	except Exception as e:
		return ActionResult(
			error=f'❌ Failed to call UIA Helper: {str(e)}',
			include_in_memory=True,
			success=False
		)


def register_uia_click(registry: Registry) -> None:
	"""
	Register the uia_click action to the tools registry.

	Usage:
		from browser_use import Tools
		from test_agent.custom_actions.uia_click import register_uia_click

		tools = Tools()
		register_uia_click(tools.registry)
	"""

	@registry.action(
		description='Click element using Windows UI Automation (real OS-level mouse click, bypasses all detection)',
		param_model=UIAClickAction,
	)
	async def uia_click(
		params: UIAClickAction,
		browser_session: BrowserSession,
	) -> ActionResult:
		"""
		Execute click using Windows UI Automation.

		This performs a real OS-level mouse click that bypasses all browser and
		JavaScript-level detection mechanisms. Edge autofill will treat this as
		a genuine user click.

		Args:
			params: Click parameters (element index)
			browser_session: Browser session

		Returns:
			ActionResult with success/error
		"""
		return await execute_uia_click(params, browser_session)
