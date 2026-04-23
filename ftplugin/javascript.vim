" FileType plugin for JavaScript/TypeScript - tmux-agent integration
" This file loads when editing JavaScript or TypeScript files

if exists('b:did_tmux_agent_ftplugin_javascript')
  finish
endif
let b:did_tmux_agent_ftplugin_javascript = 1

" Only load if tmux-agent is available
if !exists('g:loaded_tmux_agent')
  finish
endif

" JavaScript-specific configuration
let b:tmux_agent_language = 'javascript'
let b:tmux_agent_comment_prefix = '//'

" Detect TypeScript
if &filetype == 'typescript' || &filetype == 'typescriptreact'
  let b:tmux_agent_language = 'typescript'
endif

" Detect JSX/TSX
if &filetype == 'javascriptreact'
  let b:tmux_agent_language = 'jsx'
elseif &filetype == 'typescriptreact'
  let b:tmux_agent_language = 'tsx'
endif

" JavaScript-specific key mappings

" Send current line or visual selection to tmux-agent
nnoremap <buffer> <silent> <leader>ta :call tmux_agent#send()<CR>
vnoremap <buffer> <silent> <leader>ta :<C-u>call tmux_agent#send_visual()<CR>

" Explain JavaScript/TypeScript code
nnoremap <buffer> <silent> <leader>te :call tmux_agent#send_with_prompt('Explain this ' . b:tmux_agent_language . ' code:')<CR>
vnoremap <buffer> <silent> <leader>te :<C-u>call tmux_agent#send_visual_with_prompt('Explain this ' . b:tmux_agent_language . ' code:')<CR>

" Generate tests for JavaScript code
nnoremap <buffer> <silent> <leader>tt :call tmux_agent#send_with_prompt('Write Jest tests for this ' . b:tmux_agent_language . ' code:')<CR>
vnoremap <buffer> <silent> <leader>tt :<C-u>call tmux_agent#send_visual_with_prompt('Write Jest tests for this ' . b:tmux_agent_language . ' code:')<CR>

" Refactor JavaScript code
nnoremap <buffer> <silent> <leader>tr :call tmux_agent#send_with_prompt('Refactor this ' . b:tmux_agent_language . ' code for better readability and modern ES6+ practices:')<CR>
vnoremap <buffer> <silent> <leader>tr :<C-u>call tmux_agent#send_visual_with_prompt('Refactor this ' . b:tmux_agent_language . ' code for better readability and modern ES6+ practices:')<CR>

" Debug JavaScript code
nnoremap <buffer> <silent> <leader>td :call tmux_agent#send_with_prompt('Help debug this ' . b:tmux_agent_language . ' code. What could be wrong?')<CR>
vnoremap <buffer> <silent> <leader>td :<C-u>call tmux_agent#send_visual_with_prompt('Help debug this ' . b:tmux_agent_language . ' code. What could be wrong?')<CR>

" Add TypeScript types
if b:tmux_agent_language == 'typescript' || b:tmux_agent_language == 'tsx'
  nnoremap <buffer> <silent> <leader>tty :call tmux_agent#send_with_prompt('Add proper TypeScript types to this code:')<CR>
  vnoremap <buffer> <silent> <leader>tty :<C-u>call tmux_agent#send_visual_with_prompt('Add proper TypeScript types to this code:')<CR>
endif

" JavaScript-specific commands
command! -buffer -range=% TmuxAgentJSExplain <line1>,<line2>call tmux_agent#send_with_prompt('Explain this ' . b:tmux_agent_language . ' code:')
command! -buffer -range=% TmuxAgentJSTest <line1>,<line2>call tmux_agent#send_with_prompt('Write Jest tests for this ' . b:tmux_agent_language . ' code:')
command! -buffer -range=% TmuxAgentJSRefactor <line1>,<line2>call tmux_agent#send_with_prompt('Refactor this ' . b:tmux_agent_language . ' code:')

if b:tmux_agent_language == 'typescript' || b:tmux_agent_language == 'tsx'
  command! -buffer -range=% TmuxAgentTSTypes <line1>,<line2>call tmux_agent#send_with_prompt('Add TypeScript types to this code:')
endif

" Auto-setup for JavaScript projects
function! s:setup_javascript_project() abort
  " Check if we're in a JavaScript project
  if filereadable('package.json') || filereadable('package-lock.json') || filereadable('yarn.lock')
    " Set project-specific settings
    let b:tmux_agent_project_type = 'javascript'
    
    " Check for framework
    if filereadable('package.json')
      try
        let package = json_decode(join(readfile('package.json'), ''))
        if has_key(package, 'dependencies')
          if has_key(package.dependencies, 'react')
            let b:tmux_agent_framework = 'react'
          elseif has_key(package.dependencies, 'vue')
            let b:tmux_agent_framework = 'vue'
          elseif has_key(package.dependencies, 'angular')
            let b:tmux_agent_framework = 'angular'
          endif
        endif
      catch
        " Ignore JSON parsing errors
      endtry
    endif
    
    " Suggest common JavaScript tasks
    if !exists('g:tmux_agent_no_javascript_suggestions')
      echo "tmux-agent: JavaScript project detected. Use <leader>te to explain, <leader>tt for tests."
      if exists('b:tmux_agent_framework')
        echo "tmux-agent: " . b:tmux_agent_framework . " framework detected."
      endif
    endif
  endif
endfunction

" Run project detection
call timer_start(100, {-> s:setup_javascript_project()})

" JavaScript-specific completion (if supported)
if exists('*tmux_agent#complete_javascript')
  setlocal omnifunc=tmux_agent#complete_javascript
endif

" Highlight JavaScript code in tmux-agent responses
if has('syntax') && exists('g:tmux_agent_syntax_highlight')
  let b:tmux_agent_syntax_lang = 'javascript'
  if b:tmux_agent_language == 'typescript'
    let b:tmux_agent_syntax_lang = 'typescript'
  endif
endif

" Cleanup when leaving buffer
augroup tmux_agent_javascript_cleanup
  autocmd! * <buffer>
  autocmd BufWinLeave <buffer> 
        \ if exists('b:tmux_agent_javascript_cleanup') |
        \   unlet b:tmux_agent_javascript_cleanup |
        \ endif
augroup END