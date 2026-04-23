#!/usr/bin/env python3
"""
Neovim remote plugin for tmux-agent.
This provides async communication between Neovim and tmux-agent.
"""

import os
import sys
import asyncio
import threading
from typing import Any, Dict, List, Optional
from pathlib import Path

# Add the plugin's python directory to the path
plugin_dir = Path(__file__).parent.parent.parent
python_dir = plugin_dir / 'python'
if str(python_dir) not in sys.path:
    sys.path.insert(0, str(python_dir))

try:
    import pynvim
    from pynvim import attach, Nvim
    HAS_PYNVIM = True
except ImportError:
    HAS_PYNVIM = False

try:
    from tmux_agent import agent
    from app import main_async
    HAS_TMUX_AGENT = True
except ImportError as e:
    print(f"Failed to import tmux-agent: {e}")
    HAS_TMUX_AGENT = False


@pynvim.plugin
class TmuxAgentPlugin:
    """Neovim plugin for tmux-agent with async support."""
    
    def __init__(self, nvim: Nvim):
        self.nvim = nvim
        self.agent = None
        self.loop = None
        self.thread = None
        self.is_running = False
        
        # Configuration from Neovim
        self.config = {
            'python_path': '',
            'default_model': 'deepseek-chat',
            'auto_open': True,
            'debug': False,
        }
        
        # Message queue for async communication
        self.message_queue = asyncio.Queue()
        
    @pynvim.function('TmuxAgentStart', sync=True)
    def start_agent(self, args: List[Any]) -> bool:
        """Start the tmux-agent in a background thread."""
        if self.is_running:
            self.nvim.out_write("tmux-agent is already running\n")
            return True
            
        if not HAS_TMUX_AGENT:
            self.nvim.err_write("tmux-agent Python module not found\n")
            return False
            
        # Load configuration from Neovim variables
        self._load_config()
        
        # Start the async loop in a separate thread
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_agent_loop,
            daemon=True
        )
        self.thread.start()
        
        self.is_running = True
        self.nvim.out_write("tmux-agent started (Neovim async mode)\n")
        return True
    
    def _load_config(self):
        """Load configuration from Neovim variables."""
        try:
            self.config['python_path'] = self.nvim.vars.get(
                'tmux_agent_python_path', ''
            )
            self.config['default_model'] = self.nvim.vars.get(
                'tmux_agent_default_model', 'deepseek-chat'
            )
            self.config['auto_open'] = bool(self.nvim.vars.get(
                'tmux_agent_auto_open', True
            ))
            self.config['debug'] = bool(self.nvim.vars.get(
                'tmux_agent_debug', False
            ))
        except Exception as e:
            if self.config['debug']:
                self.nvim.err_write(f"Error loading config: {e}\n")
    
    def _run_agent_loop(self):
        """Run the asyncio event loop in a background thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._agent_main())
    
    async def _agent_main(self):
        """Main async agent loop."""
        try:
            # Initialize the agent
            self.agent = agent
            
            # Process messages from the queue
            while self.is_running:
                try:
                    # Wait for a message with timeout
                    message = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=1.0
                    )
                    
                    if message['type'] == 'query':
                        await self._process_query(message)
                    elif message['type'] == 'command':
                        await self._process_command(message)
                    elif message['type'] == 'stop':
                        break
                        
                except asyncio.TimeoutError:
                    # Timeout is fine, just check if we should continue
                    continue
                except Exception as e:
                    if self.config['debug']:
                        self._echo_error(f"Error in agent loop: {e}")
                    
        except Exception as e:
            self._echo_error(f"Fatal error in agent loop: {e}")
        finally:
            self.is_running = False
    
    async def _process_query(self, message: Dict[str, Any]):
        """Process a query from Neovim."""
        query = message.get('query', '')
        callback = message.get('callback')
        
        if not query or not self.agent:
            return
            
        try:
            # Get response from agent
            response_text = ""
            async for chunk in self.agent.stream_response(query):
                response_text += chunk
                
                # Send chunks back to Neovim as they arrive (async)
                if callback and chunk.strip():
                    self._schedule_callback(callback, {'chunk': chunk})
            
            # Send final response
            if callback:
                self._schedule_callback(callback, {
                    'complete': True,
                    'full_response': response_text
                })
                
        except Exception as e:
            if self.config['debug']:
                self._echo_error(f"Error processing query: {e}")
            if callback:
                self._schedule_callback(callback, {
                    'error': str(e)
                })
    
    async def _process_command(self, message: Dict[str, Any]):
        """Process a command from Neovim."""
        command = message.get('command', '')
        args = message.get('args', [])
        callback = message.get('callback')
        
        try:
            if command == 'switch_model':
                model = args[0] if args else self.config['default_model']
                self.agent.switch_model(model)
                result = f"Switched to model: {model}"
                
            elif command == 'get_model_info':
                info = self.agent.get_model_info()
                result = info
                
            elif command == 'list_models':
                models = self.agent.list_available_models()
                result = models
                
            elif command == 'clear_history':
                self.agent.clear_messages()
                result = "History cleared"
                
            else:
                result = f"Unknown command: {command}"
                
            if callback:
                self._schedule_callback(callback, {'result': result})
                
        except Exception as e:
            if self.config['debug']:
                self._echo_error(f"Error processing command: {e}")
            if callback:
                self._schedule_callback(callback, {'error': str(e)})
    
    def _schedule_callback(self, callback: str, data: Dict[str, Any]):
        """Schedule a callback to be executed in Neovim's thread."""
        # Use Neovim's async API to call back into Vimscript
        def _callback():
            try:
                # Convert data to a format Neovim can handle
                import json
                data_json = json.dumps(data)
                self.nvim.call(callback, data_json)
            except Exception as e:
                if self.config['debug']:
                    self.nvim.err_write(f"Callback error: {e}\n")
        
        # Schedule the callback in Neovim's thread
        self.nvim.async_call(_callback)
    
    def _echo_error(self, message: str):
        """Send an error message to Neovim."""
        def _echo():
            self.nvim.err_write(f"tmux-agent: {message}\n")
        self.nvim.async_call(_echo)
    
    @pynvim.function('TmuxAgentQuery', sync=False)
    def query_agent(self, args: List[Any], callback: str):
        """Send a query to tmux-agent (async)."""
        if not self.is_running:
            self.nvim.err_write("tmux-agent is not running. Call TmuxAgentStart() first.\n")
            return
            
        query = args[0] if args else ''
        if not query:
            self.nvim.err_write("No query provided\n")
            return
            
        # Add query to the queue
        asyncio.run_coroutine_threadsafe(
            self.message_queue.put({
                'type': 'query',
                'query': query,
                'callback': callback
            }),
            self.loop
        )
    
    @pynvim.function('TmuxAgentCommand', sync=False)
    def send_command(self, args: List[Any], callback: str):
        """Send a command to tmux-agent (async)."""
        if not self.is_running:
            self.nvim.err_write("tmux-agent is not running\n")
            return
            
        command = args[0] if args else ''
        command_args = args[1:] if len(args) > 1 else []
        
        if not command:
            self.nvim.err_write("No command provided\n")
            return
            
        # Add command to the queue
        asyncio.run_coroutine_threadsafe(
            self.message_queue.put({
                'type': 'command',
                'command': command,
                'args': command_args,
                'callback': callback
            }),
            self.loop
        )
    
    @pynvim.function('TmuxAgentStop', sync=True)
    def stop_agent(self, args: List[Any]) -> bool:
        """Stop the tmux-agent."""
        if not self.is_running:
            return True
            
        # Send stop message
        asyncio.run_coroutine_threadsafe(
            self.message_queue.put({'type': 'stop'}),
            self.loop
        )
        
        # Wait for thread to finish
        if self.thread:
            self.thread.join(timeout=2.0)
            
        self.is_running = False
        self.nvim.out_write("tmux-agent stopped\n")
        return True
    
    @pynvim.function('TmuxAgentStatus', sync=True)
    def get_status(self, args: List[Any]) -> Dict[str, Any]:
        """Get the status of tmux-agent."""
        return {
            'running': self.is_running,
            'config': self.config,
            'has_agent': HAS_TMUX_AGENT,
            'has_pynvim': HAS_PYNVIM
        }
    
    @pynvim.autocmd('VimLeavePre', pattern='*', sync=True)
    def on_vim_leave(self):
        """Clean up when Neovim exits."""
        if self.is_running:
            self.stop_agent([])


# Neovim remote plugin registration
if __name__ == '__main__':
    # This is executed when Neovim loads the remote plugin
    if HAS_PYNVIM:
        # Register the plugin with Neovim
        plugin = TmuxAgentPlugin
        
        # For testing/debugging
        if __name__ == '__main__' and len(sys.argv) > 1:
            if sys.argv[1] == 'test':
                print("tmux-agent Neovim plugin module loaded successfully")
                print(f"Has pynvim: {HAS_PYNVIM}")
                print(f"Has tmux-agent: {HAS_TMUX_AGENT}")
    else:
        print("ERROR: pynvim not installed. Neovim remote plugin cannot function.")
        print("Install with: pip install pynvim")