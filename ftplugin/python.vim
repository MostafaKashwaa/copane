" FileType plugin for Python - copane integration
" This file loads when editing Python files

if exists('b:did_copane_ftplugin_python')
  finish
endif
let b:did_copane_ftplugin_python = 1

" Only load if copane is available
if !exists('g:loaded_copane')
  finish
endif

" Python-specific configuration
let b:copane_language = 'python'
let b:copane_comment_prefix = '#'

" Python-specific key mappings
" These only work in Python buffers

" Send current line or visual selection to copane
nnoremap <buffer> <silent> <leader>ta :call tmux_agent#send()<CR>
vnoremap <buffer> <silent> <leader>ta :<C-u>call tmux_agent#send_visual()<CR>

" Explain Python code
nnoremap <buffer> <silent> <leader>te :call tmux_agent#send_with_prompt('Explain this Python code:')<CR>
vnoremap <buffer> <silent> <leader>te :<C-u>call tmux_agent#send_visual_with_prompt('Explain this Python code:')<CR>

" Generate tests for Python code
nnoremap <buffer> <silent> <leader>tt :call tmux_agent#send_with_prompt('Write unit tests for this Python code:')<CR>
