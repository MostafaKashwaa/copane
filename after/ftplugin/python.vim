" After plugin for Python - Compatibility fixes for copane
" This loads AFTER all other Python ftplugins

" Only proceed if copane is loaded
if !exists('g:loaded_copane')
  finish
endif

" Compatibility with python-mode
if exists('g:pymode') && g:pymode
  " python-mode might use <leader>r, so we should check
  if maparg('<leader>r', 'n') =~? 'pymode'
    " Suggest alternative mapping
    echo "copane: python-mode detected. <leader>r is used by python-mode."
    if exists('g:copane_mapping_prefix')
      echo "copane: Using " . g:copane_mapping_prefix . "m for model info instead."
    endif
  endif
  
  " Use python-mode's Python executable if available
  if exists('g:pymode_python')
    let g:copane_python_path = g:pymode_python
  endif
endif

" Compatibility with jedi-vim
if exists('g:loaded_jedi') && g:loaded_jedi
  " Share Python path with jedi
  if exists('g:jedi#environment_path')
    let g:copane_python_path = g:jedi#environment_path
  endif
endif

" Compatibility with ALE
if exists('g:loaded_ale')
  " ALE might have linting on save, ensure copane doesn't interfere
  if exists('b:ale_linters')
    " Add copane as a potential suggestion source
    if index(b:ale_linters, 'copane') == -1
      " copane can provide AI-powered suggestions
      let b:ale_linters = b:ale_linters + ['copane']
    endif
  endif
endif

" Compatibility with coc.nvim
if exists('g:did_coc_loaded')
  " coc.nvim has extensive Python support
  " Ensure copane commands don't conflict with coc actions
  
  " Check for coc-python
  if exists('*coc#rpc#start_server')
    " coc.nvim is running, add integration
    command! -buffer CopaneCocExplain call tmux_agent#send_with_prompt('Explain this Python code. Consider coc.nvim context:')
    
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
    let g:copane_python_path = venv_python
    echo "copane: Using virtualenv Python: " . venv_python
  endif
endif

" Compatibility with conda
if exists('$CONDA_PREFIX')
  " Use conda's Python if available
  let conda_python = $CONDA_PREFIX . '/bin/python'
  if executable(conda_python)
    let g:copane_python_path = conda_python
    echo "copane: Using conda Python: " . conda_python
  endif
endif

" Fix for common Python plugin conflicts
function! s:fix_python_conflicts() abort
  let prefix = get(g:, 'copane_mapping_prefix', '<leader>t')
  
  " Check for conflicting mappings
  let conflicts = []
  
  " Check <prefix>s (send)
  let send_map = prefix . 's'
  if maparg(send_map, 'n') != '' && maparg(send_map, 'n') !~? 'copane'
    call add(conflicts, send_map . ': ' . maparg(send_map, 'n'))
  endif
  
  " Check <prefix>o (open)
  let open_map = prefix . 'o'
  if maparg(open_map, 'n') != '' && maparg(open_map, 'n') !~? 'copane'
    call add(conflicts, open_map . ': ' . maparg(open_map, 'n'))
  endif
  
  " Report conflicts
  if !empty(conflicts)
    echo "copane: Found mapping conflicts:"
    for conflict in conflicts
      echo "  " . conflict
    endfor
    echo "copane: Consider changing copane mappings in your vimrc:"
    echo "  let g:copane_mapping_prefix = '<leader>at'"
  endif
endfunction

" Run conflict check after a short delay
call timer_start(500, {-> s:fix_python_conflicts()})

" Integration with Python-specific tools
function! s:setup_python_tools() abort
  " Check for black, isort, pylint, mypy
  let python_tools = {}
  
  " Check for black
  if executable('black')
    let python_tools.black = 1
    command! -buffer CopaneBlackFix call tmux_agent#send_with_prompt('Fix Python code formatting to follow black style:')
  endif
  
  " Check for isort
  if executable('isort')
    let python_tools.isort = 1
    command! -buffer CopaneImportSort call tmux_agent#send_with_prompt('Sort Python imports according to isort conventions:')
  endif
  
  " Check for pylint
  if executable('pylint')
    let python_tools.pylint = 1
    command! -buffer CopanePylintCheck call tmux_agent#send_with_prompt('Check this Python code for pylint issues and fix them:')
  endif
  
  " Check for mypy
  if executable('mypy')
    let python_tools.mypy = 1
    command! -buffer CopaneTypeCheck call tmux_agent#send_with_prompt('Add type hints and fix mypy issues in this Python code:')
  endif
  
  " Store available tools
  if !empty(python_tools)
    let b:copane_python_tools = python_tools
    if !exists('g:copane_no_suggestions') || !g:copane_no_suggestions
      echo "copane: Detected Python tools: " . join(keys(python_tools), ', ')
    endif
  endif
endfunction

" Setup Python tools
call timer_start(1000, {-> s:setup_python_tools()})

" Cleanup
augroup copane_python_after_cleanup
  autocmd! * <buffer>
  autocmd BufWinLeave <buffer>
        \ if exists('b:copane_python_tools') |
        \   unlet b:copane_python_tools |
        \ endif
augroup END
