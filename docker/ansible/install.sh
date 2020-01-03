#!/usr/bin/env bash

if [[ ! -f './local_bin/docker-ansible.sh' ]]; then
    echo "! You must be in anryko/ansible source code directory to run this script!"
    echo "! You are trying to run it from $PWD."
    echo "! Installation FAILED!"
    exit 1
fi

brew_install() {
    brew list | grep $1 >/dev/null \
        || { echo "* Installing brew $1..."; brew install $1; }
}

echo "* Create $HOME/bin directory."
mkdir -p ~/bin
echo "* Copy scripts:"
cp -Pav local_bin/* ~/bin/ | sed 's/^/  /'

if [[ :"$PATH": == *:'~/bin':*
        || :"$PATH": == *:'$HOME/bin':*
        || :"$PATH": == *:"$HOME/bin":* ]]; then
    echo "* Installation finished."
    exit 0
fi

# Attempt to figure out present lowest priority shell profile.
if [[ -f ~/.profile ]]; then
    shell_env_file="$HOME/.profile"
elif [[ -f ~/.bashrc ]]; then
    shell_env_file="$HOME/.bashrc"
else
    shell_env_file="$HOME/.bash_profile"
fi

new_path='PATH=~/bin:$PATH'
echo "* Append $HOME/bin PATH to $shell_env_file."
echo -e "\n$new_path" >> "$shell_env_file"

echo "* Installation finished."
echo "+ Changes will be in effect after you open a new shell \
or run 'source $shell_env_file' from the current one."
