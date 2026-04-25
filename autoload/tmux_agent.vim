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
  let l:cmd = 'tmux display -p -t ' . a:pane_id . ' "#{pane_id}" 2>/dev/null'
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

" Run the setup script, capturing and displaying its output so the user
" sees progress and any errors.
function! s:run_setup_script() abort
  let l:plugin_dir = expand('<sfile>:p:h') . '/..'
  let l:setup_script = l:plugin_dir . '/setup_python.sh'

  if !filereadable(l:setup_script)
    echohl ErrorMsg
    echo 'copane: setup_python.sh not found at ' . l:setup_script
    echohl None
    return 0
  endif

  " Check if bash is available
  if !executable('bash')
    echohl ErrorMsg
    echo 'copane: bash not found (required by setup_python.sh)'
    echohl None
    return 0
  endif

  let l:cmd = 'bash ' . shellescape(l:setup_script) . ' 2>&1'
  let l:output = system(l:cmd)
  let l:exit_code = v:shell_error

  " Display the script output to the user (strip ANSI escape codes for Vim)
  if !empty(l:output)
    " Strip ANSI color codes
    let l:clean = substitute(l:output, '\e\[[0-9;]*m', '', 'g')
    " Display each line
    for l:line in split(l:clean, "\n")
      if !empty(l:line)
        echo l:line
      endif
    endfor
  endif

  return l:exit_code == 0
endfunction

" Ensure the virtual environment exists and is usable.
function! s:ensure_python_setup() abort
  " Already checked this Vim session and succeeded
  if exists('s:python_ready') && s:python_ready
    return 1
  endif

  " If the venv's python binary exists, we're good to go
  let l:venv_python = g:copane_venv_dir . '/bin/python3'
  if executable(l:venv_python)
    let s:python_ready = 1
    return 1
  endif

  " Otherwise, try to run the setup script
  echohl WarningMsg
  echo 'copane: Setting up Python environment (one-time)...'
  echohl None

  let l:success = s:run_setup_script()

  if l:success
    let l:venv_python = g:copane_venv_dir . '/bin/python3'
    if executable(l:venv_python)
      let s:python_ready = 1
      echohl MoreMsg
      echo 'copane: Python environment ready.'
      echohl None
      return 1
    endif
  endif

  " If we got here, setup failed
  echohl ErrorMsg
  echo 'copane: Python setup failed.'
  echo '       Run :CopaneSetupPython or execute setup_python.sh manually.'
  echohl None
  return 0
endfunction

" ============================================================================
" PUBLIC FUNCTIONS
" ============================================================================

" Manually trigger Python setup (for :CopaneSetupPython)
function! tmux_agent#setup_python() abort
  echohl WarningMsg
  echo 'copane: Running Python setup...'
  echohl None

  let l:success = s:run_setup_script()

  if l:success
    let l:venv_python = g:copane_venv_dir . '/bin/python3'
    if executable(l:venv_python)
      let s:python_ready = 1
      echohl MoreMsg
      echo 'copane: Python setup complete.'
      echohl None
      return 1
    endif
  endif

  echohl ErrorMsg
  echo 'copane: Python setup failed.'
  echohl None
  return 0
endfunction

" Build the command to launch the copane Python app.
" Includes the environment file path if set.
function! s:build_start_command() abort
  let l:venv_python = g:copane_venv_dir . '/bin/python3'
  let l:plugin_dir = expand('<sfile>:p:h') . '/..'

  if executable(l:venv_python)
    let l:cmd = l:venv_python . ' -m copane.app'
  elseif filereadable(l:plugin_dir . '/python/src/copane/app.py')
    let l:cmd = 'python3 -m copane.app --no-banner'
  else
    return $SHELL
  endif

  " Pass the user-configured env file path, if set
  if exists('g:copane_env_file') && !empty(g:copane_env_file)
    let l:cmd .= ' --env-file ' . shellescape(g:copane_env_file)
  endif

  return l:cmd
endfunction

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

  " If the pane exists, move it to the current window and select it.
  if !empty(l:pane_id) && s:pane_exists(l:pane_id)
    " Check if it's already in the current window
    let l:current_window = trim(system('tmux display -p "#{window_id}"'))
    let l:pane_window = trim(system('tmux display -p -t ' . shellescape(l:pane_id) . ' "#{window_id}"'))
    
    if l:pane_window == l:current_window
      " Pane is already in the current window, just select it
      call system('tmux select-pane -t ' . l:pane_id)
      echohl Title
      echo 'copane: Focused existing pane ' . l:pane_id
      echohl None
      return
    else
    " Move the pane to the current window
      let l:split_flag = '-h'
      if g:copane_split_direction ==# 'horizontal'
        let l:split_flag = '-v'
      elseif g:copane_split_direction ==# 'below'
        let l:split_flag = '-v'
      endif
      call system('tmux join-pane ' . l:split_flag . ' -l ' . g:copane_split_size . ' -s ' . l:pane_id)
      call system('tmux select-pane -t ' . l:pane_id)
      echohl Title
      echo 'copane: Moved existing pane to current window' . l:pane_id
      echohl None
      return
    endif
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
    let l:start_cmd = s:build_start_command()
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
  
  if !s:pane_exists(l:pane_id)
    echohl WarningMsg
    echo 'copane: ' . l:pane_id . ' does not exist, clearing stored ID'
    echohl None
    call s:clear_pane_id()
    return
  endif

  let l:kill_result = system('tmux kill-pane -t ' . l:pane_id)
  if v:shell_error != 0
    echohl ErrorMsg
    echo 'copane: Failed to kill pane ' . l:pane_id
    echohl None
    return
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

function! s:wait_for_pane_ready(pane_id, timeout_ms) abort
  let l:start_time = reltime()
  while reltimefloat(reltime(l:start_time)) < a:timeout_ms / 1000.0
    let l:content = system('tmux capture-pane -p -t ' . a:pane_id . ' -S -50')
    if stridx(l:content, '__COPANE_READY__') >= 0 
      return 1
    endif
    sleep 100m
  endwhile
  return 0
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
    call s:wait_for_pane_ready(l:pane_id, 5000) " Wait up to 5 seconds for the pane to be ready
  endif
  
  " If the caller provided text, use it. Otherwise, send the entire buffer
  " with context.
  if a:0 >= 1
    let l:text = a:1
  else
    let l:text = join(getline(1, '$'), "\n")
    let l:filepath = expand('%:p')
    if !empty(l:filepath)
      let l:text = 'File: ' . l:filepath . "\n\n```\n" . l:text . "\n```"
    endif
  endif

  let l:escaped = shellescape(l:text)

  call system('tmux set-buffer -b copane_send ' . l:escaped)
  call system('tmux paste-buffer -b copane_send -t ' . l:pane_id)
  call system('tmux send-keys -t ' . l:pane_id . '  C-j')

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
  call system('tmux send-keys -t ' . l:pane_id . ' /modelinfo C-j')
endfunction

function! tmux_agent#switch_model(model_key) abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    echohl WarningMsg
    echo 'copane: No pane open. Use :CopaneOpen first.'
    echohl None
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' /switch ' . a:model_key . ' C-j')
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
  call system('tmux send-keys -t ' . l:pane_id . ' /models C-j')
endfunction

" ============================================================================
" UTILITY FUNCTIONS
" ============================================================================

function! tmux_agent#clear_history() abort
  let l:pane_id = s:get_stored_pane_id()
  if empty(l:pane_id)
    return
  endif
  call system('tmux send-keys -t ' . l:pane_id . ' /clear C-j')
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
  echo 'Env file: ' . get(g:, 'copane_env_file', '(not set)')
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
