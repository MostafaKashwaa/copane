" After plugin for Python - Compatibility fixes for tmux-agent
" This loads AFTER all other Python ftplugins

" Only proceed if tmux-agent is loaded
if !exists('g:loaded_tmux_agent')
  finish
endif

" Compatibility with python-mode
if exists('g:pymode') && g:pymode
  " python-mode uses <leader>r for run, so avoid conflict
  if maparg('<leader>tr', 'n') =~? 'tmux_agent'
    " python-mode might use <leader>r, so we should check
    if maparg('<leader>r', 'n') =~? 'pymode'
      " Suggest alternative mapping
      echo "tmux-agent: python-mode detected. <leader>r is used by python-mode."
      echo "tmux-agent: Using <leader>ta for tmux-agent instead."
    endif
  endif
  
  " Use python-mode's Python executable if available
  if exists('g:pymode_python')
    let g:tmux_agent_python_path = g:pymode_python
  endif
endif

" Compatibility with jedi-vim
if exists('g:loaded_jedi') && g:loaded_jedi
  " jedi-vim uses <leader>d for goto, avoid conflict
  if maparg('<leader>td', 'n') =~? 'tmux_agent'
    " Check if jedi uses <leader>d
    if maparg('<leader>d', 'n') =~? 'jedi'
      echo "tmux-agent: jedi-vim detected. <leader>d is used by jedi for goto."
      echo "tmux-agent: Consider using <leader>tdb for debug instead."
    endif
  endif
  
  " Share Python path with jedi
  if exists('g:jedi#environment_path')
    let g:tmux_agent_python_path = g:jedi#environment_path
  endif
endif

" Compatibility with ALE
if exists('g:loaded_ale')
  " ALE might have linting on save, ensure tmux-agent doesn't interfere
  if exists('b:ale_linters')
    " Add tmux-agent as a potential suggestion source
    if index(b:ale_linters, 'tmux-agent') == -1
      " tmux-agent can provide AI-powered suggestions
      let b:ale_linters = b:ale_linters + ['tmux-agent-suggestions']
    endif
  endif
endif

" Compatibility with coc.nvim
if exists('g:did_coc_loaded')
  " coc.nvim has extensive Python support
  " Ensure tmux-agent commands don't conflict with coc actions
  
  " Check for coc-python
  if exists('*coc#rpc#start_server')
    " coc.nvim is running, add integration
    command! -buffer TmuxAgentCocExplain call tmux_agent#send_with_prompt('Explain this Python code. Consider coc.nvim context:')
    
    " Use coc.nvim's Python interpreter if available
    if exists('b:coc_node_path')
      " Not directly applicable, but shows integration pattern
    endif
  endif
endif

" Compatibility with virtualenv
if exists('$VIRTUAL_ENV')
  " Use virtualenv's Python if available
  let venv_python = $VIRTUAL_ENV . '/bin/python'
  if executable(venv_python)
    let g:tmux_agent_python_path = venv_python
    echo "tmux-agent: Using virtualenv Python: " . venv_python
  endif
endif

" Compatibility with conda
if exists('$CONDA_PREFIX')
  " Use conda's Python if available
  let conda_python = $CONDA_PREFIX . '/bin/python'
  if executable(conda_python)
    let g:tmux_agent_python_path = conda_python
    echo "tmux-agent: Using conda Python: " . conda_python
  endif
endif

" Fix for common Python plugin conflicts
function! s:fix_python_conflicts() abort
  " Check for conflicting mappings
  let conflicts = []
  
  " Check <leader>te (explain)
  if maparg('<leader>te', 'n') =~? 'tmux_agent'
    let other_map = maparg('<leader>te', 'n')
    if other_map != '' && other_map !~? 'tmux_agent'
      call add(conflicts, '<leader>te: ' . other_map)
    endif
  endif
  
  " Check <leader>tt (test)
  if maparg('<leader>tt', 'n') =~? 'tmux_agent'
    let other_map = maparg('<leader>tt', 'n')
    if other_map != '' && other_map !~? 'tmux_agent'
      call add(conflicts, '<leader>tt: ' . other_map)
    endif
  endif
  
  " Report conflicts
  if !empty(conflicts)
    echo "tmux-agent: Found mapping conflicts:"
    for conflict in conflicts
      echo "  " . conflict
    endfor
    echo "tmux-agent: Consider changing tmux-agent mappings in your vimrc:"
    echo "  let g:tmux_agent_mapping_prefix = '<leader>at'  " Use <leader>ate, <leader>att, etc."
  endif
endfunction

" Run conflict check after a short delay
call timer_start(500, {-> s:fix_python_conflicts()})

" Integration with Python-specific tools
function! s:setup_python_tools() abort
  " Check for black, isort, pylint, etc.
  let python_tools = {}
  
  " Check for black
  if executable('black')
    let python_tools.black = 1
    command! -buffer TmuxAgentBlackFix call tmux_agent#send_with_prompt('Fix Python code formatting to follow black style:')
  endif
  
  " Check for isort
  if executable('isort')
    let python_tools.isort = 1
    command! -buffer TmuxAgentImportSort call tmux_agent#send_with_prompt('Sort Python imports according to isort conventions:')
  endif
  
  " Check for pylint
  if executable('pylint')
    let python_tools.pylint = 1
    command! -buffer TmuxAgentPylintCheck call tmux_agent#send_with_prompt('Check this Python code for pylint issues and fix them:')
  endif
  
  " Check for mypy
  if executable('mypy')
    let python_tools.mypy = 1
    command! -buffer TmuxAgentTypeCheck call tmux_agent#send_with_prompt('Add type hints and fix mypy issues in this Python code:')
  endif
  
  " Store available tools
  if !empty(python_tools)
    let b:tmux_agent_python_tools = python_tools
    if !exists('g:tmux_agent_no_tool_suggestions')
      echo "tmux-agent: Detected Python tools: " . join(keys(python_tools), ', ')
    endif
  endif
endfunction

" Setup Python tools
call timer_start(1000, {-> s:setup_python_tools()})

" Cleanup
augroup tmux_agent_python_after_cleanup
  autocmd! * <buffer>
  autocmd BufWinLeave <buffer>
        \ if exists('b:tmux_agent_python_tools') |
        \   unlet b:tmux_agent_python_tools |
        \ endif
augroup END
