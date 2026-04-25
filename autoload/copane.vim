" ============================================================================
" copane.vim — Autoload functions for copane commands
" ============================================================================

" Resolve the model config file path (must match tmux_agent.py logic)
function! copane#model_config_path() abort
  let l:config_dir = expand('~/.config/tmux-agent')
  return l:config_dir . '/model_config.json'
endfunction

" Open the model configuration file for editing
function! copane#edit_model_config() abort
  let l:path = copane#model_config_path()
  let l:dir = fnamemodify(l:path, ':h')

  " Ensure the directory exists
  if !isdirectory(l:dir)
    call mkdir(l:dir, 'p')
  endif

  " Create the file if it doesn't exist (write an empty JSON object)
  if !filereadable(l:path)
    call writefile(['{}'], l:path)
  endif

  execute 'edit ' . l:path
  echohl MoreMsg
  echo 'copane: Editing model config (' . l:path . ')'
  echohl None
endfunction

" Open the secrets / env file for editing
function! copane#edit_secrets() abort
  let l:path = expand(g:copane_env_file)
  let l:dir = fnamemodify(l:path, ':h')

  " Ensure the directory exists
  if !isdirectory(l:dir)
    call mkdir(l:dir, 'p')
  endif

  " Create the file if it doesn't exist, with a template comment
  if !filereadable(l:path)
    call writefile([
          \ '# copane API keys',
          \ '# Copy .env.example entries here',
          \ '',
          \ 'OPENAI_API_KEY=',
          \ 'DEEPSEEK_API_KEY=',
          \ 'ANTHROPIC_API_KEY=',
          \ 'GROQ_API_KEY=',
          \ 'OPENROUTER_API_KEY=',
          \ 'GOOGLE_API_KEY=',
          \ 'GITHUB_API_KEY=',
          \ 'ANYSCALE_API_KEY=',
          \ 'XAI_API_KEY=',
          \ 'COHERE_API_KEY=',
          \ 'PERPLEXITY_API_KEY=',
          \ 'MISTRAL_API_KEY=',
          \ 'VOYAGE_API_KEY=',
          \ 'CUSTOM_ENDPOINT=',
          \ 'CUSTOM_API_KEY=',
          \ ], l:path)
  endif

  execute 'edit ' . l:path
  echohl MoreMsg
  echo 'copane: Editing secrets (' . l:path . ')'
  echohl None
endfunction
