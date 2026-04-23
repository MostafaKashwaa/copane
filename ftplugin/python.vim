" FileType plugin for Python - tmux-agent integration
" This file loads when editing Python files

if exists('b:did_tmux_agent_ftplugin_python')
  finish
endif
let b:did_tmux_agent_ftplugin_python = 1

" Only load if tmux-agent is available
if !exists('g:loaded_tmux_agent')
  finish
endif

" Python-specific configuration
let b:tmux_agent_language = 'python'
let b:tmux_agent_comment_prefix = '#'

" Python-specific key mappings
" These only work in Python buffers

" Send current line or visual selection to tmux-agent
nnoremap <buffer> <silent> <leader>ta :call tmux_agent#send()<CR>
vnoremap <buffer> <silent> <leader>ta :<C-u>call tmux_agent#send_visual()<CR>

" Explain Python code
nnoremap <buffer> <silent> <leader>te :call tmux_agent#send_with_prompt('Explain this Python code:')<CR>
vnoremap <buffer> <silent> <leader>te :<C-u>call tmux_agent#send_visual_with_prompt('Explain this Python code:')<CR>

" Generate tests for Python code
nnoremap <buffer> <silent> <leader>tt :call tmux_agent#send_with_prompt('Write unit tests for this Python code:')<CR>
vnoremap <buffer> <silent> <leader>tt :<C-u>call tmux_agent#send_visual_with_prompt('Write unit tests for this Python code:')<CR>

" Refactor Python code
nnoremap <buffer> <silent> <leader>tr :call tmux_agent#send_with_prompt('Refactor this Python code for better readability and performance:')<CR>
vnoremap <buffer> <silent> <leader>tr :<C-u>call tmux_agent#send_visual_with_prompt('Refactor this Python code for better readability and performance:')<CR>

" Debug Python code
nnoremap <buffer> <silent> <leader>td :call tmux_agent#send_with_prompt('Help debug this Python code. What could be wrong?')<CR>
vnoremap <buffer> <silent> <leader>td :<C-u>call tmux_agent#send_visual_with_prompt('Help debug this Python code. What could be wrong?')<CR>

" Document Python code
nnoremap <buffer> <silent> <leader>tdoc :call tmux_agent#send_with_prompt('Add comprehensive docstrings to this Python code:')<CR>
vnoremap <buffer> <silent> <leader>tdoc :<C-u>call tmux_agent#send_visual_with_prompt('Add comprehensive docstrings to this Python code:')<CR>

" Python-specific commands
command! -buffer -range=% TmuxAgentPythonExplain <line1>,<line2>call tmux_agent#send_with_prompt('Explain this Python code:')
command! -buffer -range=% TmuxAgentPythonTest <line1>,<line2>call tmux_agent#send_with_prompt('Write unit tests for this Python code:')
command! -buffer -range=% TmuxAgentPythonRefactor <line1>,<line2>call tmux_agent#send_with_prompt('Refactor this Python code:')
command! -buffer TmuxAgentPythonImportHelp call tmux_agent#send('What Python imports do I need for this code?')

" Auto-setup for Python projects
function! s:setup_python_project() abort
  " Check if we're in a Python project
  if filereadable('pyproject.toml') || filereadable('requirements.txt') || filereadable('setup.py')
    " Set project-specific settings
    let b:tmux_agent_project_type = 'python'
    
    " Suggest common Python tasks
    if !exists('g:tmux_agent_no_python_suggestions')
      echo "tmux-agent: Python project detected. Use <leader>te to explain, <leader>tt for tests."
    endif
  endif
endfunction

" Run project detection
call timer_start(100, {-> s:setup_python_project()})

" Python-specific completion (if supported)
if exists('*tmux_agent#complete_python')
  setlocal omnifunc=tmux_agent#complete_python
endif

" Highlight Python code in tmux-agent responses
if has('syntax') && exists('g:tmux_agent_syntax_highlight')
  let b:tmux_agent_syntax_lang = 'python'
endif

" Cleanup when leaving buffer
augroup tmux_agent_python_cleanup
  autocmd! * <buffer>
  autocmd BufWinLeave <buffer> 
        \ if exists('b:tmux_agent_python_cleanup') |
        \   unlet b:tmux_agent_python_cleanup |
        \ endif
augroup END