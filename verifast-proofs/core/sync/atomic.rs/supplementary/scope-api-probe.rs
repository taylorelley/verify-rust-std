pub fn scope_api() {
    std::thread::scope(|scope| {
        scope.spawn(|| ());
    });
}
