" ============================================================================
" tmux-agent / copane — Autoload Functions
" ============================================================================
" This file provides the core pane management logic.
" Functions are lazy-loaded only when called.

" ============================================================================
" CONFIGURATION (with defaults)
" ============================================================================

if !exists('g:copane_tmux_pane_name')
  let g:copane_tmux_pane_name = 'copane'
endif

if !exists('g:copane_split_direction')
  let g:copane_split_direction = 'vertical'
endif

if !exists('g:copane_split_size')
  let g:copane_split_size = '33%'
endif

if !exists('g:copane_start_command')
  let g:copane_start_command = ''
endif

if !exists('g:copane_pane_scope')
  " 'window' = one pane per tmux window (default)
  " 'session' = one pane for the entire tmux session
  let g:copane_pane_scope = 'session'
endif

" ============================================================================
" INTERNAL HELPERS
" ============================================================================

" Get the option name used to store the pane ID based on scope
function! s:pane_option_name() abort
  return '@copane_pane'
endfunction

" Get stored pane ID from tmux
function! s:get_stored_pane_id() abort
  if g:copane_pane_scope ==# 'session'
    let l:cmd = 'tmux show-options -g ' . s:pane_option_name()
  else
    let l:cmd = 'tmux show-options -w ' . s:pane_option_name()
  endif
  let l:result = system(l:cmd)
  if v:shell_error != 0 || empty(trim(l:result))
    return ''
  endif
  let l:parts = split(trim(l:result))
  if len(l:parts) >= 2
    return l:parts[-1]
  endif
  return ''
endfunction

" Store a pane ID in tmux options
function! s:store_pane_id(pane_id) abort
  if g:copane_pane_scope ==# 'session'
    call system('tmux set-option -g ' . s:pane_option_name() . ' ' . a:pane_id)
  else
    call system('tmux set-option -w ' . s:pane_option_name() . ' ' . a:pane_id)
  endif
endfunction

" Remove the stored pane ID
function! s:clear_pane_id() abort
  if g:copane_pane_scope ==# 'session'
    call system('tmux set-option -gu ' . s:pane_option_name())
  else
    call system('tmux set-option -wu ' . s:pane_option_name())
  endif
endfunction

" Verify a pane ID still exists in the current session
function! s:pane_exists(pane_id) abort
  if empty(a:pane_id)
    return 0
  endif
  let l:cmd = 'tmux list-panes -a -F "#{pane_id}" 2>/dev/null | grep -Fx ' . shellescape(a:pane_id)
  let l:result = system(l:cmd)
  return v:shell_error == 0 && !empty(trim(l:result))
endfunction

" Check if we are currently INSIDE the copane pane
function! s:inside_copane_pane() abort
  let l:stored = s:get_stored_pane_id()
  if empty(l:stored)
    return 0
  endif
  return $TMUX_PANE ==# l:stored
endfunction

" Get the current tmux window's panes
function! s:get_current_pane_id() abort
  return trim(system('tmux display -p "#{pane_id}"'))
endfunction

" ============================================================================
" PYTHON SETUP (auto on first use)
" ============================================================================

" Ensure the virtual environment exists and is usable.
" This only checks for the venv’s python binary – no import test needed.
" The import inside Vim is handled by plugin/copane.vim.
function! s:ensure_python_setup() abort
  " Already checked this Vim session and succeeded
  if exists('s:python_ready') && s:python_ready
    return 1
  endif

  " If the venv’s python binary exists, we’re good to go
  let l:venv_python = g:copane_venv_dir . '/bin/python3'
  if executable(l:venv_python)
    let s:python_ready = 1
    return 1
  endif

  " Otherwise, try to run the setup script
  echohl WarningMsg
  echo 'copane: Setting up Python environment (one-time)...'
  echohl None

  let l:plugin_dir = expand('<sfile>:p:h') . '/..'
  let l:setup_script = l:plugin_dir . '/setup_python.sh'

  if filereadable(l:setup_script)
    let l:cmd = 'bash ' . shellescape(l:setup_script)
    call system(l:cmd)
    if v:shell_error == 0
      " Re-check after setup
      let l:venv_python = g:copane_venv_dir . '/bin/python3'
      if executable(l:venv_python)
        let s:python_ready = 1
        echohl MoreMsg
        echo 'copane: Python environment ready.'
        echohl None
        return 1
      endif
    endif
  endif

  " If we got here, setup failed
  echohl ErrorMsg
  echo 'copane: Python setup failed. Run setup_python.sh manually.'
  echohl None
  return 0
endfunction

" ============================================================================
" PUBLIC FUNCTIONS
" ============================================================================

" Open (create or focus) the copane pane
function! tmux_agent#open() abort
  " Ensure Python environment is set up before creating pane
  if !s:ensure_python_setup()
    echohl ErrorMsg
    echo 'copane: Cannot open pane — Python setup failed. Run :CopaneSetupPython'
    echohl None
    return
  endif

  " Step 1: Check if we already have a stored pane that still exists
  let l:pane_id = s:get_stored_pane_id()
  
  if !empty(l:pane_id) && s:pane_exists(l:pane_id)
    call system('tmux select-pane -t ' . l:pane_id)
    echohl Title
    echo 'copane: Selected existing pane ' . l:pane_id
    echohl None
    return
  endif
  
  " Step 2: Clear stale stored ID
  call s:clear_pane_id()
  
  " Step 3: Create a new pane
  let l:split_flag = '-h'
  if g:copane_split_direction ==# 'horizontal'
    let l:split_flag = '-v'
  elseif g:copane_split_direction ==# 'below'
    let l:split_flag = '-v'
  endif
  
  " Build the command to run in the new pane
  let l:start_cmd = g:copane_start_command
  if empty(l:start_cmd)
    " Default: run the copane app using the venv Python if available
    let l:venv_python = g:copane_venv_dir . '/bin/python3'
    let l:plugin_dir = expand('<sfile>:p:h') . '/..'

    " Prefer running the module via th venv Python
    if executable(l:venv_python)
      let l:start_cmd = l:venv_python . ' -m copane.app'
    elseif filereadable(l:plugin_dir . '/python/src/copane/app.py')
      let l:start_cmd = 'python3 -m copane.app --no-banner'
    else
      let l:start_cmd = $SHELL
    endif
    
  endif
  
  let l:create_cmd = 'tmux split-window ' . l:split_flag
        \ . ' -l ' . g:copane_split_size
        \ . ' -c "#{pane_current_path}"'
        \ . ' -P -F "#{pane_id}"'
        \ . ' ' . l:start_cmd
  
  let l:new_pane_id = trim(system(l:create_cmd))
  
  if v:shell_error != 0 || empty(l:new_pane_id)
    echohl ErrorMsg
    echo 'copane: Failed to create pane: ' . l:create_cmd
    echohl None
    return
  endif
  
  " Step 4: Store the pane ID
  call s:store_pane_id(l:new_pane_id)
  
  " Step 5: Rename the pane
  call system('tmux select-pane -t ' . l:new_pane_id . ' -T "🤖 copane"')
  
  echohl Title
  echo 'copane: Created pane ' . l:new_pane_id
  echohl None
endfunction

" Close the copane pane
function! tmux_agent#close() abort
  let l:pane_id = s:get_stored_pane_id()
  
  if empty(l:pane_id)
    echohl WarningMsg
    echo 'copane: No pane to close'
    echohl None
    return
  endif
  
  if s:pane_exists(l:pane_id)
    call system('tmux kill-pane -t ' . l:pane_id)
  endif
  
  call s:clear_pane_id()
  
  echohl Title
  echo 'copane: Pane closed'
  echohl None
endfunction

" Toggle between copane pane and the previous pane
function! tmux_agent#toggle() abort
  if s:inside_copane_pane()
    call system('tmux select-pane -l')
  else
    call tmux_agent#open()
  endif
endfunction

" Send text to the copane pane
function! tmux_agent#send(...) abort
  let l:pane_id = s:get_stored_pane_id()
  
  if empty(l:pane_id) || !s:pane_exists(l:pane_id)
    call tmux_agent#open()
    let l:pane_id = s:get_stored_pane_id()
    if empty(l:pane_id)
      return
    endif
    sleep 500m
  endif
  
  if a:0 >= 1
    let l:text = a:1
  else
    let l:text = join(getline(1, '$'), "\n")
    let l:filepath = expand('%:p')
    if !empty(l:filepath)
      let l:text = 'File: ' . l:filepath . "\n\n```\n" . l:text . "\n```"
    endif
  endif
  
  call system('tmux send-keys -t ' . l:pane_id . ' C-c')
  sleep 100m
  call system('tmux send-keys -t ' . l:pane_id . ' -l ' . shellescape(l:text))
  call system('tmux send-keys -t ' . l:pane_id . ' Enter')
  
  echohl Comment
  echo 'copane: Sent ' . len(l:text) . ' chars to pane ' . l:pane_id
  echohl None
endfunction

" Send visual selection to copane pane
function! tmux_agent#send_visual() range
  let l:text = join(getline(a:firstline, a:lastline), "\n")
  let l:filepath = expand('%:p')
  if !empty(l:filepath)
    let l:context = 'File: ' . l:filepath . ' (lines ' . a:firstline . '-' . a:lastline . ')' . "\n\n```\n" . l:text . "\n```"
  else
    let l:context = "```\n" . l:text . "\n```"
  endif
  call tmux_agent#send(l:context)
endfunction

" Send text with a custom prompt
function! tmux_agent#send_with_prompt(prompt) abort
  let l:text = join(getline(1, '$'), "\n")
  let l:filepath = expand('%:p')
  if !empty(l:filepath)
    let l:full = a:prompt . "\n\nFile: " . l:filepath . "\n\n```\n" . l:text . "\n```"
  else
    let l:full = a:prompt . "\n\n```\n" . l:text . "\n```"
  endif
  call tmux_agent#send(l:full)
endfunction

" Send visual selection with a custom prompt
function! tmux_agent#send_visual_with_prompt(prompt) range
  let l:text = join(getline(a:firstline, a:lastline), "\n")
  let l:filepath = expand('%:p')
  if !empty(l:filepath)
    let l:full = a:prompt . "\n\nFile: " . l:filepath . ' (lines ' . a:firstline . '-' . a:lastline . ')' . "\n\n```\n" . l:text . "\n```"
  else
    let l:full = a:prompt . "\n\n```\n" . l:text . "\n```"
  endif
  call tmux_agent#send(l:full)
endfunction

" ============================================================================
" MODEL MANAGEMENT FUNCTIONS
" ============================================================================

function! tmux_agent#model_info() abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    echohl WarningMsg
    echo 'copane: No pane open. Use :CopaneOpen first.'
    echohl None
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' C-c')
  sleep 100m
  call system('tmux send-keys -t ' . l:pane_id . ' /modelinfo Enter')
endfunction

function! tmux_agent#switch_model(model_key) abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    echohl WarningMsg
    echo 'copane: No pane open. Use :CopaneOpen first.'
    echohl None
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' C-c')
  sleep 100m
  call system('tmux send-keys -t ' . l:pane_id . ' /switch ' . a:model_key . ' Enter')
  echohl Title
  echo 'copane: Switching to model: ' . a:model_key
  echohl None
endfunction

function! tmux_agent#list_models() abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    echohl WarningMsg
    echo 'copane: No pane open. Use :CopaneOpen first.'
    echohl None
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' C-c')
  sleep 100m
  call system('tmux send-keys -t ' . l:pane_id . ' /models Enter')
endfunction

" ============================================================================
" UTILITY FUNCTIONS
" ============================================================================

function! tmux_agent#clear_history() abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' C-c')
  sleep 100m
  call system('tmux send-keys -t ' . l:pane_id . ' /clear Enter')
  echohl Title
  echo 'copane: History cleared'
  echohl None
endfunction

function! tmux_agent#help() abort
  echohl Title
  echo '=== copane Help ==='
  echohl None
  echo ':CopaneOpen         - Open/focus the AI pane'
  echo ':CopaneClose        - Close the AI pane'
  echo ':CopaneToggle       - Toggle between editor and AI pane'
  echo ':CopaneSend         - Send current buffer to AI'
  echo ":'<,'>CopaneSend     - Send visual selection to AI"
  echo ':CopaneModelInfo    - Show current AI model'
  echo ':CopaneSwitchModel <key> - Switch model'
  echo ':CopaneListModels   - List available models'
  echo ':CopaneClearHistory - Clear conversation'
  echo ':CopaneSetupPython   - (Re)install Python dependencies'
  echo ':CopaneHelp         - Show this help'
  echo ''
  echo 'Mappings: <leader>to = Open, <leader>tc = Close'
  echo '          <leader>ts = Send, <leader>tm = Model info'
  echo ''
  echo 'Note: Python setup runs automatically on first :CopaneOpen.'
endfunction

function! tmux_agent#debug_info() abort
  echohl Title
  echo '=== copane Debug Info ==='
  echohl None
  echo 'Stored pane ID: ' . s:get_stored_pane_id()
  echo 'Pane exists: ' . s:pane_exists(s:get_stored_pane_id())
  echo 'Current $TMUX_PANE: ' . $TMUX_PANE
  echo 'Inside copane pane: ' . s:inside_copane_pane()
  echo 'Scope: ' . g:copane_pane_scope
  echo 'Split: ' . g:copane_split_direction . ' (' . g:copane_split_size . ')'
  echo 'Venv dir: ' . g:copane_venv_dir
  echo 'Python ready: ' . (exists('s:python_ready') && s:python_ready ? 'yes' : 'no')
  echohl Title
  echo '=== copane Options ==='
  echohl None
  echo 'g:copane_tmux_pane_name = ' . g:copane_tmux_pane_name
  echo 'g:copane_split_direction = ' . g:copane_split_direction
  echo 'g:copane_split_size = ' . g:copane_split_size
  echo 'g:copane_start_command = ' . g:copane_start_command
  echo 'g:copane_pane_scope = ' . g:copane_pane_scope
  echo 'g:copane_venv_dir = ' . g:copane_venv_dir
endfunction
